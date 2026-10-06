"""
Context Guard — Role Workflow Verification

Drives the full investigation lifecycle against the real Flask app and MongoDB:

    analyst drafts and submits a report
      → compliance reviews it, curates the vault and requests restricted information
        → administrator approves, with a scope and an expiry
          → compliance reads the released information and continues the case

Plus the security assertions: 403s, refusal to self-approve, expiry enforcement, and
the audit trail that every one of those actions must leave behind.

    cd backend && python test_workflow.py
"""

import sys
from datetime import datetime, timedelta

from app import create_app, init_database
from config import get_db
from services.seed import seed_database
from services.seed_access import ensure_evidence_baselines, ensure_restricted_information
from services.users import ensure_case_assignments, ensure_users

PASSED, FAILED = [], []


def check(label, condition, detail=""):
    if condition:
        PASSED.append(label)
        print(f"  PASS  {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL  {label}  {detail}")


def reset_to_known_state():
    """Re-seed so the run is deterministic, and clear anything a previous run created."""
    db = get_db()
    db.users.delete_many({"is_synthetic": False})
    db.sessions.delete_many({})
    db.settings.delete_many({})
    db.analyst_reports.delete_many({})
    db.case_evidence.delete_many({})
    db.investigation_updates.delete_many({})
    db.access_requests.delete_many({})
    db.access_authorizations.delete_many({})
    # The trail is append-only for the running system, not for a fixture reset: a
    # deterministic run needs to start from an empty log.
    db.audit_log.delete_many({})
    db.restricted_subject_information.delete_many({})
    db.notifications.delete_many({})
    seed_database(db)
    ensure_users(db)
    ensure_case_assignments(db)
    ensure_restricted_information(db)
    ensure_evidence_baselines(db)
    print(f"  Reset: {db.cases.count_documents({})} cases, "
          f"{db.case_evidence.count_documents({})} evidence items, "
          f"{db.restricted_subject_information.count_documents({})} restricted records")


def main():
    print("── Bootstrapping ─────────────────────────────────────────────")
    reset_to_known_state()
    init_database()
    db = get_db()
    app = create_app()
    c = app.test_client()

    def login(identifier, password):
        r = c.post("/api/auth/login", json={"username": identifier, "password": password})
        body = r.get_json() or {}
        return r.status_code, body.get("token"), body.get("user") or {}

    def hdr(token):
        return {"Authorization": f"Bearer {token}"}

    tokens = {}
    users = {}
    for identifier, password in [
        ("analyst@contextguard.demo", "analyst123"),
        ("compliance@contextguard.demo", "compliance123"),
        ("admin@contextguard.demo", "admin123"),
    ]:
        status, token, user = login(identifier, password)
        tokens[identifier.split("@")[0]] = token
        users[identifier.split("@")[0]] = user
        check(f"{identifier} signs in by email", status == 200 and token is not None, status)

    A, C, ADM = tokens["analyst"], tokens["compliance"], tokens["admin"]

    print("\n── Analyst: investigation and report ─────────────────────────")
    r = c.post("/api/cases/case_2/analyst-report",
               headers=hdr(A), json={"build_from_case": True})
    report = (r.get_json() or {}).get("report") or {}
    report_id = report.get("id")
    check("analyst drafts a report on an assigned case", r.status_code == 201, r.status_code)
    check("draft version starts at 1", report.get("version") == 1)
    check("draft is unlocked while it is a draft", report.get("locked") is False)
    check("draft is prefilled from stored evidence",
          len(report.get("findings", [])) >= 5, len(report.get("findings", [])))
    check("every finding carries a classification",
          all(f.get("classification") in ("observed_fact", "model_inference",
                                          "analyst_observation", "recommended_next_step")
              for f in report.get("findings", [])))
    check("model inferences are separated from observed facts",
          report["finding_groups"]["observed_fact"] and report["finding_groups"]["model_inference"])
    check("the report carries the no-guilt notice",
          "does not establish" in (report.get("notice") or ""))
    check("report cites its sources",
          any(f.get("source") for f in report.get("findings", [])))
    check("analyst cannot draft on an unassigned case",
          c.post("/api/cases/case_3/analyst-report", headers=hdr(A),
                 json={}).status_code == 403)

    r = c.patch(f"/api/reports/{report_id}", headers=hdr(A), json={
        "append_finding": {
            "classification": "analyst_observation",
            "statement": "I telephoned the branch: the co-pay was settled at the hospital counter.",
            "source": "analyst telephone note",
        },
    })
    edited = (r.get_json() or {}).get("report") or {}
    check("analyst adds an observation", r.status_code == 200 and any(
        f["classification"] == "analyst_observation" for f in edited.get("findings", [])))
    check("an invalid classification is refused",
          c.patch(f"/api/reports/{report_id}", headers=hdr(A), json={
              "findings": [{"classification": "accusation", "statement": "x"}],
          }).status_code == 409)

    # Opening the case is part of the investigation, and it is what puts Case opened
    # in the trail.
    opened = c.get("/api/cases/case_2", headers=hdr(A)).get_json() or {}
    check("analyst opens the assigned case", opened.get("id") == "case_2", opened.get("id"))
    check("the open case reports the analyst's workflow position",
          bool((opened.get("workflow") or {}).get("status")))

    r = c.post(f"/api/analyst/reports/{report_id}/submit", headers=hdr(A))
    submitted = (r.get_json() or {}).get("report") or {}
    check("analyst submits the report", r.status_code == 200, r.status_code)
    check("submitted report is locked", submitted.get("locked") is True)
    check("submission records the timestamp", bool(submitted.get("submitted_at")))
    check("submission records the analyst identity",
          submitted.get("analyst_name") == users["analyst"]["name"])
    check("the case moves to Analyst Report Submitted",
          db.cases.find_one({"id": "case_2"}).get("status") == "analyst_report_submitted",
          db.cases.find_one({"id": "case_2"}).get("status"))

    r = c.patch(f"/api/reports/{report_id}", headers=hdr(A), json={"summary": "rewrite"})
    check("a submitted version cannot be edited", r.status_code == 409, r.status_code)
    check("the stored version is unchanged",
          db.analyst_reports.find_one({"id": report_id}).get("summary") != "rewrite")

    r = c.post(f"/api/analyst/reports/{report_id}/amend", headers=hdr(A),
               json={"reason": "Hospital has now issued the final invoice."})
    amended = (r.get_json() or {}).get("report") or {}
    check("amending opens version 2", r.status_code == 201 and amended.get("version") == 2)
    check("version 2 points back at version 1", amended.get("supersedes") == report_id)
    check("the original version survives",
          db.analyst_reports.find_one({"id": report_id}) is not None)
    check("amendment without a reason is refused",
          c.post(f"/api/analyst/reports/{report_id}/amend", headers=hdr(A), json={}).status_code == 400)

    check("analyst cannot open the admin user list",
          c.get("/api/admin/users", headers=hdr(A)).status_code == 403)
    check("analyst cannot open the compliance review queue",
          c.get("/api/compliance/reports", headers=hdr(A)).status_code == 403)
    check("analyst cannot open the compliance update feed",
          c.get("/api/compliance/updates", headers=hdr(A)).status_code == 403)
    check("analyst cannot approve an access request",
          c.post("/api/access-requests/REQ-ANY/approve", headers=hdr(A), json={}).status_code in (403, 404))
    # Asking is not authority. An analyst may raise a request for information held back
    # from them, and is still refused the information itself until somebody releases it.
    requested = c.post("/api/access-requests", headers=hdr(A), json={
        "case_id": "case_2", "categories": ["identity"],
        "reason": "The counterparty's identity is missing from the file.",
        "necessity": "It cannot be established from the records already released."})
    check("an analyst may raise a request for restricted information",
          requested.status_code == 201, requested.status_code)
    locked_view = c.get("/api/restricted/case_2", headers=hdr(A))
    check("restricted information stays withheld until it is released",
          locked_view.status_code == 200 and (locked_view.get_json() or {}).get("locked") is True,
          locked_view.status_code)

    print("\n── Compliance: review, vault, request ────────────────────────")
    r = c.get("/api/compliance/reports", headers=hdr(C))
    queue = (r.get_json() or {}).get("reports", [])
    check("submitted report appears in the compliance queue",
          any(item["id"] == report_id for item in queue), len(queue))
    check("compliance can read the submitted version",
          c.get(f"/api/reports/{report_id}", headers=hdr(C)).status_code == 200)
    check("compliance can request a clarification",
          c.post(f"/api/analyst/reports/{report_id}/clarification", headers=hdr(C),
                 json={"note": "Please attach the discharge summary."}).status_code == 200)
    check("clarification without a note is refused",
          c.post(f"/api/analyst/reports/{report_id}/clarification", headers=hdr(C),
                 json={}).status_code == 400)
    check("compliance accepts the report",
          c.post(f"/api/analyst/reports/{report_id}/review", headers=hdr(C),
                 json={"outcome": "accepted", "note": "Sufficient for review."}).status_code == 200)

    r = c.get("/api/cases/case_2/evidence", headers=hdr(C))
    vault = r.get_json() or {}
    check("evidence vault opens for compliance", r.status_code == 200)
    check("vault was seeded with stored records", len(vault.get("items", [])) > 0,
          len(vault.get("items", [])))
    check("vault exposes the folder tree", len(vault.get("summary", {}).get("folders", [])) > 0)
    check("restricted items are placeholders before authorisation",
          all(item.get("locked") for item in vault.get("items", [])
              if item.get("access_level") == "restricted"))

    r = c.post("/api/cases/case_2/evidence", headers=hdr(C), json={
        "folder": "compliance_notes", "type": "compliance_note",
        "title": "Insurance claim verified with the insurer",
        "description": "Claim reference matches the hospital invoice on file.",
    })
    note_id = (r.get_json() or {}).get("item", {}).get("id")
    check("compliance files a note in the vault", r.status_code == 201, r.status_code)
    check("evidence carries provenance",
          (r.get_json() or {}).get("item", {}).get("created_by_name") == users["compliance"]["name"])

    r = c.post(f"/api/evidence/{note_id}/supersede", headers=hdr(C),
               json={"title": "Insurance claim verified with the insurer (revised)",
                     "description": "Second call confirmed the claim reference."})
    replacement = (r.get_json() or {}).get("item") or {}
    check("a corrected item becomes a new version", r.status_code == 200 and replacement.get("version") == 2)
    check("the superseded item is retained, not overwritten",
          db.case_evidence.find_one({"id": note_id}).get("status") == "superseded")
    check("the replacement links back", replacement.get("supersedes") == note_id)

    r = c.get("/api/cases/case_2/timeline", headers=hdr(C))
    timeline = r.get_json() or {}
    kinds = {event["kind"] for event in timeline.get("events", [])}
    check("timeline reconstructs the case", r.status_code == 200 and len(kinds) >= 3, sorted(kinds))

    r = c.get("/api/cases/case_2/updates", headers=hdr(C))
    check("compliance sees the case update feed",
          len((r.get_json() or {}).get("updates", [])) > 0)
    feed = c.get("/api/compliance/updates", headers=hdr(C)).get_json() or {}
    check("compliance sees the cross-case update feed", "updates" in feed)
    check("the report submission is an update",
          any(u["type"] == "analyst_report" for u in feed.get("updates", [])))
    first_update = feed.get("updates", [{}])[0].get("id")
    check("an update can be acknowledged",
          c.post(f"/api/updates/{first_update}/acknowledge", headers=hdr(C),
                 json={"note": "Reviewed."}).status_code == 200)

    r = c.post("/api/access-requests", headers=hdr(C), json={
        "case_id": "case_2", "categories": ["contact", "external_reference"],
        "reason": "To establish whether the co-pay was funded from a verified source.",
        "necessity": "The bank response does not identify the funding source of the payment.",
        "related_finding": "Contextual gap: funding source unverified.",
        "duration_days": 7,
    })
    request_doc = (r.get_json() or {}).get("request") or {}
    request_id = request_doc.get("id")
    check("compliance creates an access request", r.status_code == 201, r.status_code)
    check("request is pending", request_doc.get("status") == "pending")
    check("request records the reason and necessity",
          bool(request_doc.get("reason")) and bool(request_doc.get("necessity")))
    check("request carries the no-determination notice",
          "No determination" in (request_doc.get("notice") or ""))
    check("request without a reason is refused",
          c.post("/api/access-requests", headers=hdr(C), json={
              "case_id": "case_2", "categories": ["identity"], "necessity": "x"}).status_code == 400)
    check("request without a necessity is refused",
          c.post("/api/access-requests", headers=hdr(C), json={
              "case_id": "case_2", "categories": ["identity"], "reason": "x"}).status_code == 400)
    check("a second open request on the same case is refused",
          c.post("/api/access-requests", headers=hdr(C), json={
              "case_id": "case_2", "categories": ["identity"], "reason": "x",
              "necessity": "y"}).status_code == 400)

    locked = c.get("/api/restricted/case_2", headers=hdr(C)).get_json() or {}
    check("restricted information stays locked while pending",
          locked.get("locked") is True and locked.get("state") == "pending", locked.get("state"))
    check("the lock explains where the request stands",
          request_id in (locked.get("reason") or ""))
    check("the matrix shows which categories exist without values",
          len(locked.get("matrix", {}).get("available", [])) >= 2)
    check("compliance cannot decide an access request",
          c.post(f"/api/access-requests/{request_id}/approve", headers=hdr(C),
                 json={"duration_days": 7}).status_code == 403)

    graph = c.get("/api/graph/entity", headers=hdr(C)).get_json() or {}
    check("graph withholds restricted subjects before authorisation",
          graph.get("restricted", {}).get("masked", 0) >= 1, graph.get("restricted"))
    check("a restricted node is labelled as such, not named",
          any(node.get("label") == "🔒 Restricted Information" for node in graph.get("nodes", [])))

    print("\n── Administrator: authorise access ───────────────────────────")
    r = c.get("/api/access-requests", headers=hdr(ADM))
    admin_view = r.get_json() or {}
    check("admin sees the access request queue",
          any(item["id"] == request_id for item in admin_view.get("requests", [])))
    check("admin holds decision rights", admin_view.get("can_decide") is True)

    check("rejection without a reason is refused",
          c.post(f"/api/access-requests/{request_id}/reject", headers=hdr(ADM),
                 json={}).status_code == 400)
    check("clarification without a note is refused",
          c.post(f"/api/access-requests/{request_id}/clarification", headers=hdr(ADM),
                 json={}).status_code == 400)
    check("an over-long duration is refused",
          c.post(f"/api/access-requests/{request_id}/approve", headers=hdr(ADM),
                 json={"duration_days": 900}).status_code == 400)

    r = c.post(f"/api/access-requests/{request_id}/approve", headers=hdr(ADM),
               json={"duration_days": 7, "scope": ["contact"],
                     "note": "Contact details only. Reference numbers not required."})
    approved = (r.get_json() or {})
    authorization = approved.get("authorization") or {}
    check("admin approves the request", r.status_code == 200, r.status_code)
    check("approval creates an authorisation record", bool(authorization.get("id")))
    check("authorisation records who approved it",
          authorization.get("approved_by_name") == users["admin"]["name"])
    check("authorisation has an expiry in the future",
          str(authorization.get("expires_at")) > datetime.utcnow().isoformat())
    check("approval narrowed the scope to what was granted",
          authorization.get("scope") == ["contact"] and "external_reference" in
          (authorization.get("revoked_scope") or []), authorization.get("scope"))
    check("authorisation states its conditions",
          "Time-limited" in (authorization.get("conditions") or ""))

    # Separation of duties, in two places: the administrator approves requests but
    # cannot raise one, and the service refuses self-approval even if one existed.
    check("admin cannot raise a restricted-information request",
          c.post("/api/access-requests", headers=hdr(ADM), json={
              "case_id": "case_2", "categories": ["identity"], "reason": "x",
              "necessity": "y"}).status_code == 403)
    db.access_requests.insert_one({
        "id": "REQ-SELF-CHECK", "case_id": "case_2",
        "requested_by": users["admin"]["id"], "requested_by_name": users["admin"]["name"],
        "status": "pending", "categories": ["identity"], "reason": "self",
        "necessity": "self", "duration_days": 7,
        "created_at": datetime.utcnow().isoformat(),
    })
    check("admin cannot approve their own request",
          c.post("/api/access-requests/REQ-SELF-CHECK/approve", headers=hdr(ADM),
                 json={"duration_days": 7}).status_code == 403)
    db.access_requests.delete_one({"id": "REQ-SELF-CHECK"})

    print("\n── Compliance: authorised access, then expiry ────────────────")
    released = c.get("/api/restricted/case_2", headers=hdr(C)).get_json() or {}
    check("authorised access opens the records", released.get("locked") is False, released.get("state"))
    check("released records carry the authorisation metadata",
          (released.get("records") or [{}])[0].get("authorization", {}).get("request_id") == request_id)
    check("only the approved scope is released",
          all(record["category"] in ("contact",) for record in released.get("records", [])),
          [r.get("category") for r in released.get("records", [])])
    check("the release reports remaining time",
          released.get("remaining", "").endswith("remaining"), released.get("remaining"))
    check("released records repeat the no-determination notice",
          "No determination" in (released.get("notice") or ""))

    authorized_graph = c.get("/api/graph/entity", headers=hdr(C)).get_json() or {}
    released_nodes = [n for n in authorized_graph.get("nodes", []) if n.get("authorized")]
    check("the graph shows authorised subjects as such",
          bool(released_nodes) and released_nodes[0].get("access_label") == "🔓 Authorized Information")
    check("the graph cites the authorisation behind the release",
          released_nodes and released_nodes[0].get("authorized_under") == request_id)

    vault_now = c.get("/api/cases/case_2/evidence", headers=hdr(C)).get_json() or {}
    check("vault opens restricted evidence while authorised",
          vault_now.get("authorization_state") == "authorized",
          vault_now.get("authorization_state"))

    # Expire the authorisation and confirm access stops.
    db.access_authorizations.update_one(
        {"id": authorization["id"]},
        {"$set": {"expires_at": (datetime.utcnow() - timedelta(hours=1)).isoformat()}},
    )
    expired = c.get("/api/restricted/case_2", headers=hdr(C)).get_json() or {}
    check("access ends automatically at expiry",
          expired.get("locked") is True and expired.get("state") == "expired",
          expired.get("state"))
    check("the expiry is explained, with the next step",
          "expired" in (expired.get("reason") or "").lower()
          and "new request" in (expired.get("reason") or "").lower(),
          expired.get("reason"))
    check("no records are returned after expiry", expired.get("records") == [])
    check("the expired authorisation is recorded as such",
          any(a.get("id") == authorization["id"] and a.get("is_active") is False
              for a in (c.get("/api/access-authorizations", headers=hdr(C)).get_json() or {})
              .get("authorizations", [])))
    vault_expired = c.get("/api/cases/case_2/evidence", headers=hdr(C)).get_json() or {}
    check("the vault re-locks restricted evidence",
          vault_expired.get("authorization_state") == "expired")

    check("a fresh request is possible after expiry",
          c.post("/api/access-requests", headers=hdr(C), json={
              "case_id": "case_2", "categories": ["contact"],
              "reason": "Follow-up on the funding source.",
              "necessity": "The earlier release has lapsed and the enquiry is still open.",
              "duration_days": 3}).status_code == 201)

    # ── Locked features and information ───────────────────────────
    # Some capabilities and some records are withheld from analyst *and* compliance
    # alike. Releasing them is not a role privilege: somebody has to be asked, in
    # writing, and has to answer on the record.
    print("\n── Locked features and information ──────────────────────────")
    locked = c.get("/api/locked-resources?case_id=case_2", headers=hdr(A))
    catalogue = (locked.get_json() or {}).get("resources") or []
    check("an analyst can see what is locked on their case",
          locked.status_code == 200 and len(catalogue) == 7, len(catalogue))
    check("every locked item names who can release it",
          all(item.get("decider") for item in catalogue))
    check("bank-held records and organisation-held capabilities are distinguished",
          {item["track"] for item in catalogue} == {"bank", "admin"},
          sorted({item["track"] for item in catalogue}))
    check("locked items start locked", all(item["state"] == "locked" for item in catalogue))

    thin = c.post("/api/access-requests", headers=hdr(A), json={
        "case_id": "case_2", "resource_keys": ["bank_ledger_detail"],
        "statement": "I need it.", "duration_days": 7})
    check("a request with a token justification is refused", thin.status_code == 400,
          thin.status_code)

    mixed = c.post("/api/access-requests", headers=hdr(A), json={
        "case_id": "case_2", "resource_keys": ["bank_ledger_detail", "unmasked_identifiers"],
        "statement": ("The open investigation into the ₹3,00,000 payment needs the bank's own "
                      "statement lines to verify the counterparty and the source of funds, and a "
                      "separate request covers anything the organisation itself holds."),
        "duration_days": 7})
    check("a request mixing two deciders is refused", mixed.status_code == 400, mixed.status_code)

    # The bank can only consent to a request it already knows about, so the case has to
    # have been through the pipeline first.
    c.post("/api/pipeline/run/case_2", headers=hdr(C))
    bank_request = c.post("/api/access-requests", headers=hdr(A), json={
        "case_id": "case_2", "resource_keys": ["bank_ledger_detail"],
        "statement": ("This supports the open investigation into the ₹3,00,000 payment the bank "
                      "reported as a context case. I need the ledger extract covering the payment "
                      "period to verify the counterparty and the source of the funds."),
        "duration_days": 7})
    bank_body = bank_request.get_json() or {}
    bank_decision = bank_body.get("bank_decision") or {}
    bank_auth = bank_body.get("authorization") or {}
    bank_request_id = (bank_body.get("request") or {}).get("id")
    check("a bank-held request is answered by the bank itself",
          bank_request.status_code == 201 and bool(bank_decision), bank_request.status_code)
    check("the bank approves a request that states a purpose it can act on",
          bank_decision.get("outcome") == "approved", bank_decision.get("outcome"))
    check("the bank states in writing what it checked",
          "consent" in (bank_decision.get("statement") or "").lower(),
          bank_decision.get("statement"))
    check("the bank's answer is attributed to the bank, not to a person",
          bool(bank_decision.get("bank_name")) and bank_decision.get("reviewer", "").endswith("consent desk"),
          bank_decision.get("reviewer"))
    check("the approval carries the capability it releases",
          "restricted:view" in (bank_auth.get("unlocks") or []), bank_auth.get("unlocks"))

    served = c.get("/api/locked-resources?case_id=case_2", headers=hdr(A)).get_json() or {}
    granted = [i for i in served.get("resources", []) if i["state"] == "granted"]
    check("the released item reads as granted",
          [i["key"] for i in granted] == ["bank_ledger_detail"], [i["key"] for i in granted])
    check("the bank's records are served, not merely promised",
          any(r["resource"] == "bank_ledger_detail" and r.get("rows")
              for r in served.get("released", [])),
          [r.get("resource") for r in served.get("released", [])])

    statements = c.get(f"/api/access-requests/{bank_request_id}/statements", headers=hdr(A))
    kinds = {s["kind"] for s in (statements.get_json() or {}).get("statements", [])}
    check("the requester's statement is recorded", "requester_statement" in kinds, sorted(kinds))
    check("the bank's statement is recorded alongside it", "bank_statement" in kinds, sorted(kinds))
    check("statements are not readable by an unrelated identity",
          c.get(f"/api/access-requests/{bank_request_id}/statements", headers=hdr(C)).status_code == 403)

    # A capability held by the organisation is released by a person, not by asking.
    analyst_case_before = c.get("/api/cases/case_2", headers=hdr(A)).get_json() or {}
    check("the analyst's identifiers are masked to begin with",
          analyst_case_before["privacy"]["level"] == "masked", analyst_case_before["privacy"]["level"])
    capability = c.post("/api/access-requests", headers=hdr(A), json={
        "case_id": "case_2", "resource_keys": ["unmasked_identifiers"],
        "statement": ("I cannot verify the counterparty against my own case file while the "
                      "identifiers are masked, and the escalation decision rests on confirming "
                      "who the payer is against the hospital's own records."),
        "duration_days": 3})
    capability_body = capability.get_json() or {}
    capability_id = (capability_body.get("request") or {}).get("id")
    check("an organisation-held capability waits for a person",
          capability.status_code == 201 and (capability_body.get("request") or {}).get("status") == "pending",
          (capability_body.get("request") or {}).get("status"))
    check("asking for it does not release it",
          (c.get("/api/cases/case_2", headers=hdr(A)).get_json() or {})["privacy"]["level"] == "masked")
    check("an identity without the approval right cannot release it",
          c.post(f"/api/access-requests/{capability_id}/approve", headers=hdr(C),
                 json={"duration_days": 3}).status_code == 403)
    approved = c.post(f"/api/access-requests/{capability_id}/approve", headers=hdr(ADM),
                      json={"duration_days": 3,
                            "note": "Justified: the escalation rests on identifying the payer."})
    check("an administrator releases the capability", approved.status_code == 200, approved.status_code)
    check("the analyst now reads the identifiers they asked for",
          (c.get("/api/cases/case_2", headers=hdr(A)).get_json() or {})["privacy"]["level"] == "full")

    after = c.get("/api/locked-resources?case_id=case_2", headers=hdr(A)).get_json() or {}
    capability_item = next((i for i in after.get("resources", [])
                            if i["key"] == "unmasked_identifiers"), {})
    check("the catalogue reports the grant with its remaining time",
          capability_item.get("state") == "granted" and bool(capability_item.get("remaining")),
          capability_item.get("state"))
    check("the session reports the released capability",
          "txn:view_unmasked" in (after.get("active_unlocks") or []), after.get("active_unlocks"))

    db.access_authorizations.update_one(
        {"request_id": capability_id},
        {"$set": {"expires_at": (datetime.utcnow() - timedelta(minutes=1)).isoformat()}},
    )
    check("the released capability lapses on its own at expiry",
          (c.get("/api/cases/case_2", headers=hdr(A)).get_json() or {})["privacy"]["level"] == "masked")

    trail = c.get("/api/admin/audit-logs", headers=hdr(ADM)).get_json() or {}
    entries = trail.get("entries", [])
    trail_actions = {e["action"] for e in entries}
    check("statements are written to the trail", "access_statement_recorded" in trail_actions,
          sorted(trail_actions)[:14])
    check("the bank's decision is written to the trail", "bank_access_decision" in trail_actions)
    check("the released capability is written to the trail", "access_capability_granted" in trail_actions)
    check("a statement is recorded in full, not as a flag",
          any(e["action"] == "access_statement_recorded" and len(e.get("detail") or "") > 120
              and "ledger" in (e.get("detail") or "").lower() for e in entries))
    check("the recorded statements are marked as record-only",
          all((e.get("metadata") or {}).get("recorded_only") for e in entries
              if e["action"] == "access_statement_recorded"))
    check("the bank's own identity is on the record",
          any(e["action"] == "bank_access_decision" and "consent desk" in (e.get("user") or "")
              for e in entries))

    # ── The bank gateway ──────────────────────────────────────────
    # A bank is not a local function call. A request for its records leaves the platform:
    # it waits, it can fail in transit, it can release only part of what was asked for,
    # and it lapses if the bank never answers inside its window.
    print("\n── The bank gateway ─────────────────────────────────────────")

    def set_gateway(**values):
        values.setdefault("bank_response_seconds", 0)
        values.setdefault("bank_response_deadline_hours", 48)
        values.setdefault("bank_failure_rate", 0.0)
        db.settings.update_one({"id": "org_settings"}, {"$set": values}, upsert=True)

    def settle_due(request_id):
        """Make the bank's answer due, then read a page — reads sweep the gateway."""
        db.access_requests.update_one({"id": request_id}, {"$set": {
            "respond_at": (datetime.utcnow() - timedelta(minutes=1)).isoformat()}})
        return c.get("/api/locked-resources?case_id=case_2", headers=hdr(A)).get_json() or {}

    def granted_keys():
        payload = c.get("/api/locked-resources?case_id=case_2", headers=hdr(A)).get_json() or {}
        return [i["key"] for i in payload.get("resources", []) if i["state"] == "granted"]

    # Latency: a request the bank has not answered yet is held, not decided.
    set_gateway(bank_response_seconds=3600)
    held = c.post("/api/access-requests", headers=hdr(A), json={
        "case_id": "case_2", "resource_keys": ["bank_counterparty_detail"],
        "statement": ("The open investigation needs the counterparty as the bank records it, "
                      "to verify who received the funds and complete the source of funds "
                      "picture before the report is finalised."),
        "duration_days": 7})
    held_body = held.get_json() or {}
    held_id = (held_body.get("request") or {}).get("id")
    check("a request the bank has not yet answered is held, not decided",
          held.status_code == 201
          and (held_body.get("request") or {}).get("status") == "awaiting_bank",
          (held_body.get("request") or {}).get("status"))
    check("the caller is told the request is with the bank",
          held_body.get("bank_state") == "awaiting", held_body.get("bank_state"))
    check("a held request carries the bank's response deadline",
          bool((held_body.get("request") or {}).get("response_deadline")))
    check("a held request releases nothing yet",
          "bank_counterparty_detail" not in granted_keys())
    check("the submission to the bank is recorded",
          "bank_gateway_awaiting" in {e["action"] for e in
              (c.get("/api/admin/audit-logs", headers=hdr(ADM)).get_json() or {}).get("entries", [])})

    # The answer, once due, is delivered on the next read.
    served_held = settle_due(held_id)
    delivered = next((i for i in served_held.get("resources", [])
                      if i["key"] == "bank_counterparty_detail"), {})
    check("a due answer is delivered and the item reads granted",
          delivered.get("state") == "granted", delivered.get("state"))
    check("the deferred answer is served with rows, not merely promised",
          any(r["resource"] == "bank_counterparty_detail"
              for r in served_held.get("released", [])),
          [r.get("resource") for r in served_held.get("released", [])])

    # Failure in transit: a failure is not a refusal, and it is retried inside the window.
    set_gateway(bank_response_seconds=3600, bank_failure_rate=1.0)
    failed = c.post("/api/access-requests", headers=hdr(A), json={
        "case_id": "case_2", "resource_keys": ["bank_source_of_funds"],
        "statement": ("The open investigation needs the source of funds declaration the bank "
                      "holds, to test the provenance of the payment against what the customer "
                      "told the bank at onboarding."),
        "duration_days": 7})
    failed_body = failed.get_json() or {}
    failed_id = (failed_body.get("request") or {}).get("id")
    check("a failed submission is held for retry, not treated as a refusal",
          failed_body.get("bank_state") == "failed"
          and (failed_body.get("request") or {}).get("status") == "awaiting_bank",
          failed_body.get("bank_state"))
    check("the transport failure is recorded against the request",
          bool((failed_body.get("request") or {}).get("bank_error")))
    check("the failed submission is written to the trail",
          "bank_gateway_failed" in {e["action"] for e in
              (c.get("/api/admin/audit-logs", headers=hdr(ADM)).get_json() or {}).get("entries", [])})

    # With the transport healthy again, the retry answers inside the window.
    set_gateway(bank_response_seconds=3600, bank_failure_rate=0.0)
    settle_due(failed_id)
    check("the retried answer is delivered inside the window",
          "bank_source_of_funds" in granted_keys())

    # Partial response: the bank releases what it can defend and names what it will not.
    set_gateway(bank_response_seconds=0)
    partial = c.post("/api/access-requests", headers=hdr(A), json={
        "case_id": "case_2",
        "resource_keys": ["bank_ledger_detail", "bank_counterparty_detail",
                          "bank_beneficial_ownership"],
        "statement": ("This supports the open investigation into the payment and the source of "
                      "funds behind it; I need the ledger, the counterparty and whatever the "
                      "bank holds on the payer."),
        "duration_days": 7})
    partial_body = partial.get_json() or {}
    partial_decision = partial_body.get("bank_decision") or {}
    partial_auth = partial_body.get("authorization") or {}
    check("the bank can approve part of a request",
          partial_decision.get("outcome") == "partially_approved",
          partial_decision.get("outcome"))
    check("the partial answer names the item it refused",
          partial_decision.get("refused_keys") == ["bank_beneficial_ownership"],
          partial_decision.get("refused_keys"))
    check("the partial authorisation covers only what was released",
          "bank_beneficial_ownership" not in (partial_auth.get("resources") or [])
          and "bank_ledger_detail" in (partial_auth.get("resources") or []),
          partial_auth.get("resources"))
    partial_item = next((i for i in (c.get("/api/locked-resources?case_id=case_2",
                                     headers=hdr(A)).get_json() or {}).get("resources", [])
                         if i["key"] == "bank_beneficial_ownership"), {})
    check("the item the bank refused reads as refused",
          partial_item.get("state") == "rejected", partial_item.get("state"))

    # Deadline: a bank that never answers does not leave the request open forever.
    set_gateway(bank_response_seconds=3600)
    lapse = c.post("/api/access-requests", headers=hdr(A), json={
        "case_id": "case_2", "resource_keys": ["bank_beneficial_ownership"],
        "statement": ("The open investigation needs the beneficial ownership declaration that "
                      "the bank holds for the receiving entity, so that the ownership chain "
                      "behind the payment can be established and recorded before the report "
                      "is finalised."),
        "duration_days": 7})
    lapse_id = ((lapse.get_json() or {}).get("request") or {}).get("id")
    check("the deadline request reaches the bank", bool(lapse_id), lapse.status_code)
    db.access_requests.update_one({"id": lapse_id}, {"$set": {
        "respond_at": None,
        "response_deadline": (datetime.utcnow() - timedelta(hours=1)).isoformat()}})
    c.get("/api/locked-resources?case_id=case_2", headers=hdr(A))
    lapsed_doc = db.access_requests.find_one({"id": lapse_id})
    check("a request the bank never answered inside the window lapses",
          lapsed_doc.get("status") == "expired", lapsed_doc.get("status"))
    check("a lapsed request releases nothing",
          not lapsed_doc.get("authorization_id"))
    lapse_kinds = {s["kind"] for s in
                   (c.get(f"/api/access-requests/{lapse_id}/statements", headers=hdr(A))
                    .get_json() or {}).get("statements", [])}
    check("the missed deadline is recorded in the bank's own words",
          "bank_statement" in lapse_kinds, sorted(lapse_kinds))
    check("the missed deadline is written to the trail",
          "bank_response_deadline_expired" in {e["action"] for e in
              (c.get("/api/admin/audit-logs", headers=hdr(ADM)).get_json() or {}).get("entries", [])})

    # Leave the organisation as it was found.
    set_gateway()

    # ── Evidence provenance ───────────────────────────────────────
    # A finding is only as good as the account of where it came from: which request,
    # which authorisation, which bank, filed by whom, and what it corrects.
    print("\n── Evidence provenance ──────────────────────────────────────")

    vault_items = (c.get("/api/cases/case_2/evidence", headers=hdr(C)).get_json()
                   or {}).get("items", [])
    filed = [i for i in vault_items if not i.get("locked")]
    check("filed evidence carries a provenance block",
          bool(filed) and all(i.get("provenance") for i in filed), len(filed))
    check("provenance names the origin and who filed it",
          all(i["provenance"].get("origin") and i["provenance"].get("filed_by", {}).get("name")
              for i in filed))
    check("provenance starts a custody chain",
          all(i["provenance"].get("chain") for i in filed))

    bank_item = next((i for i in filed if i["folder"] == "bank_reports"), None)
    check("a bank response is attributed to the bank, with the request that produced it",
          bank_item is not None
          and bank_item["provenance"]["origin"] == "bank_response"
          and bool(bank_item["provenance"].get("request_id")),
          (bank_item or {}).get("provenance", {}).get("origin"))

    custody = c.get(f"/api/evidence/{bank_item['id']}/provenance", headers=hdr(C))
    custody_body = custody.get_json() or {}
    check("the provenance of a record is readable in full",
          custody.status_code == 200 and bool(custody_body.get("custody")))
    check("provenance resolves the records it points at",
          all(link.get("exists") is not False for link in custody_body.get("links", []))
          and bool(custody_body.get("links")),
          custody_body.get("links"))

    # Correcting a record must not erase what it corrected.
    case_item = next((i for i in filed if i["folder"] == "transaction_evidence"), None)
    if case_item:
        corrected = c.post(f"/api/evidence/{case_item['id']}/supersede", headers=hdr(C), json={
            "description": "Corrected: the amount was transcribed from the wrong leg.",
            "reason": "Transcription error identified during review."})
        replacement = (corrected.get_json() or {}).get("item") or {}
        check("a correction files a version that names what it supersedes",
              corrected.status_code == 200
              and replacement.get("provenance", {}).get("chain", [{}])[-1].get("step") == "supersedes",
              corrected.status_code)
        original_after = db.case_evidence.find_one({"id": case_item["id"]})
        check("the corrected record keeps its custody history and points forward",
              original_after.get("status") == "superseded"
              and original_after.get("superseded_by") == replacement.get("id")
              and any(s["step"] == "superseded"
                      for s in original_after.get("provenance", {}).get("chain", [])))

    released_records = (c.get("/api/locked-resources?case_id=case_2", headers=hdr(A))
                        .get_json() or {}).get("released", [])
    check("a released bank record carries its own provenance",
          bool(released_records)
          and all(r.get("provenance", {}).get("origin") == "bank_release"
                  for r in released_records),
          [(r.get("resource"), (r.get("provenance") or {}).get("origin"))
           for r in released_records])
    check("the released record names the request and the authorisation behind it",
          bool(released_records)
          and all(r["provenance"].get("request_id") and r["provenance"].get("authorization_id")
                  for r in released_records))

    # ── Pagination ────────────────────────────────────────────────
    # Lists grow: a case accumulates transactions, the trail accumulates years. Every
    # list endpoint takes a window, and says what the window is a window of.
    print("\n── Pagination ───────────────────────────────────────────────")

    all_txns = c.get("/api/transactions", headers=hdr(C))
    check("a bare-array list still returns the shape its callers expect",
          isinstance(all_txns.get_json(), list))
    check("a windowed list reports its size in response headers",
          all_txns.headers.get("X-Total-Count") is not None
          and all_txns.headers.get("X-Has-More") in ("true", "false"))
    total_txns = int(all_txns.headers["X-Total-Count"])
    check("an unpaged list returns everything up to the cap",
          len(all_txns.get_json()) == min(total_txns, 50),
          (len(all_txns.get_json()), total_txns))

    first_page = c.get("/api/transactions?limit=2", headers=hdr(C))
    first_rows = first_page.get_json()
    check("limit windows the list", len(first_rows) == 2, len(first_rows))
    check("the headers describe the window",
          first_page.headers["X-Limit"] == "2" and first_page.headers["X-Offset"] == "0")
    check("the window says more remains when it does",
          (first_page.headers["X-Has-More"] == "true") == (total_txns > 2))

    second_rows = c.get("/api/transactions?limit=2&offset=2", headers=hdr(C)).get_json()
    check("offset advances the window without overlap",
          {t["id"] for t in first_rows}.isdisjoint({t["id"] for t in second_rows}),
          (len(first_rows), len(second_rows)))

    capped = c.get("/api/transactions?limit=100000", headers=hdr(C))
    check("an absurd page size is clamped rather than honoured",
          int(capped.headers["X-Limit"]) <= 500, capped.headers["X-Limit"])

    audit_page = c.get("/api/audit-logs?limit=5", headers=hdr(C)).get_json() or {}
    pager = audit_page.get("pagination") or {}
    check("an object-shaped list carries a pagination block",
          pager.get("limit") == 5 and pager.get("total", 0) >= pager.get("returned", 0), pager)
    check("has_more agrees with the totals it reports",
          pager.get("has_more") == (pager.get("offset", 0) + pager.get("returned", 0)
                                    < pager.get("total", 0)))
    check("a page never claims to be the whole log when it is not",
          pager.get("returned", 0) == len(audit_page.get("entries", [])))

    admin_page = (c.get("/api/admin/audit-logs?limit=5&offset=5", headers=hdr(ADM))
                  .get_json() or {}).get("pagination") or {}
    check("the administrator trail pages by offset too",
          admin_page.get("limit") == 5 and admin_page.get("offset") == 5, admin_page)

    inbox = c.get("/api/notifications?limit=3", headers=hdr(C)).get_json() or {}
    check("the notification inbox pages",
          (inbox.get("pagination") or {}).get("limit") == 3)

    cases_page = c.get("/api/cases?limit=1", headers=hdr(C))
    check("the case list windows with headers and keeps its array shape",
          isinstance(cases_page.get_json(), list) and len(cases_page.get_json()) == 1
          and int(cases_page.headers["X-Total-Count"]) >= 1)

    vault_page = c.get("/api/cases/case_2/evidence?limit=2", headers=hdr(C)).get_json() or {}
    check("the vault pages, while its summary still counts the whole vault",
          (vault_page.get("pagination") or {}).get("limit") == 2
          and vault_page.get("summary", {}).get("total", 0)
              >= (vault_page.get("pagination") or {}).get("returned", 0))

    print("\n── Administrator: console endpoints ──────────────────────────")
    r = c.get("/api/admin/system-status", headers=hdr(ADM))
    status_body = r.get_json() or {}
    check("admin reads system status", r.status_code == 200)
    check("status reports users by role", set(status_body.get("users", {}).get("by_role", {})) ==
          {"analyst", "compliance", "admin"})
    check("status reports access-control state",
          "pending_requests" in status_body.get("access_control", {}))
    check("status states that bank connectivity is simulated",
          status_body.get("integrations", {}).get("live_payment_integration") is False)
    check("compliance cannot read system status",
          c.get("/api/admin/system-status", headers=hdr(C)).status_code == 403)

    r = c.get("/api/admin/audit-logs", headers=hdr(ADM))
    logs = r.get_json() or {}
    actions = {entry["action"] for entry in logs.get("entries", [])}
    for expected in ("report_created", "report_submitted", "evidence_added", "access_request_created",
                     "access_request_approved", "restricted_accessed", "restricted_denied",
                     "case_opened", "graph_viewed"):
        check(f"audit trail records {expected}", expected in actions, sorted(actions)[:12])
    check("audit entries carry a result field",
          all("result" in entry for entry in logs.get("entries", [])))
    check("denied access is counted", logs.get("counts", {}).get("denied", 0) >= 1)
    check("restricted reads are counted", logs.get("counts", {}).get("restricted", 0) >= 1)
    check("audit entries link back to their case",
          any(entry.get("case_id") == "case_2" for entry in logs.get("entries", [])))
    check("compliance cannot open the admin audit console",
          c.get("/api/admin/audit-logs", headers=hdr(C)).status_code == 403)

    print("\n── Notifications ─────────────────────────────────────────────")
    comp_notes = c.get("/api/notifications", headers=hdr(C)).get_json() or {}
    types = {n["type"] for n in comp_notes.get("notifications", [])}
    check("compliance is notified of the submitted report", "analyst_report" in types, sorted(types))
    check("the requester is notified of the decision", "access_approved" in types, sorted(types))
    admin_notes = c.get("/api/notifications", headers=hdr(ADM)).get_json() or {}
    check("admin is notified of a new access request",
          any(n["type"] == "access_request" for n in admin_notes.get("notifications", [])))
    check("analyst is notified of the clarification",
          any(n["type"] == "clarification" for n in
              (c.get("/api/notifications", headers=hdr(A)).get_json() or {}).get("notifications", [])))
    first_note = (comp_notes.get("notifications") or [{}])[0].get("id")
    r = c.post(f"/api/notifications/{first_note}/read", headers=hdr(C))
    check("a notification can be marked read", r.status_code == 200)
    check("unread count drops", (r.get_json() or {}).get("unread", 99) < comp_notes.get("unread", 0))
    check("another user's notification cannot be read",
          c.post(f"/api/notifications/{first_note}/read", headers=hdr(A)).status_code == 404)

    print("\n── Hospital scenario and existing flows still work ───────────")
    r = c.post("/api/pipeline/ingest", headers=hdr(A), json={"scenario": "high_value"})
    ingest = r.get_json() or {}
    check("hospital payment still routes to context verification",
          ingest.get("route") == "context_verification", ingest.get("route"))
    live_case = (ingest.get("case") or {}).get("id")
    check("a case is still created for the hospital payment", bool(live_case))

    r = c.post(f"/api/pipeline/run/{live_case}", headers=hdr(A))
    trace = (r.get_json() or {}).get("trace") or []
    check("the 12-stage pipeline still completes", r.status_code == 200 and len(trace) == 12)
    sections = [(r.get_json() or {}).get("report", {}).get("sections", [])]
    check("hospital context still appears in the report",
          any(s.get("title") == "Context Returned by Bank" for s in sections[0]),
          [s.get("title") for s in sections[0]])

    vault_after = c.get(f"/api/cases/{live_case}/evidence", headers=hdr(A)).get_json() or {}
    check("bank responses from the pipeline are filed as evidence",
          any(item.get("folder") == "bank_reports" for item in vault_after.get("items", [])))
    updates_after = c.get(f"/api/cases/{live_case}/updates", headers=hdr(A)).get_json() or {}
    check("the pipeline posts investigation updates",
          any(u.get("type") == "bank_report" for u in updates_after.get("updates", [])))

    check("case 1 still stands down", (
        c.post("/api/pipeline/ingest", headers=hdr(A), json={"scenario": "routine"}).get_json()
    ).get("route") == "no_action")
    check("coordinated scenario still routes to investigation", (
        c.post("/api/pipeline/ingest", headers=hdr(C), json={"scenario": "coordinated"}).get_json()
    ).get("route") == "investigation")
    # A decision is stage 12 and rests on the stage-10 report, so the case has to have been
    # through the pipeline before it can be decided.
    check("a decision is refused while the case has no report",
          c.post("/api/cases/case_3/decision", headers=hdr(C), json={
              "decision": "escalate_compliance",
              "rationale": "Escalating with nothing to decide on."}).status_code == 409)
    check("the case can be run through the pipeline",
          c.post("/api/pipeline/run/case_3", headers=hdr(C)).status_code == 200)
    check("the decision workflow still works",
          c.post("/api/cases/case_3/decision", headers=hdr(C), json={
              "decision": "escalate_compliance",
              "rationale": "Cross-bank layering corroborated by two banks."}).status_code == 200)

    print("\n── Status workflow ───────────────────────────────────────────")
    r = c.post("/api/cases/case_1/status", headers=hdr(C), json={"status": "monitoring"})
    check("compliance can move a case to monitoring", r.status_code == 200, r.status_code)
    # Forward jumps between stages are allowed for the roles that may set them, so the
    # illegal move to prove here is a backward one: correcting history is an
    # administrator action.
    check("an illegal backward move is refused",
          c.post("/api/cases/case_1/status", headers=hdr(C),
                 json={"status": "new"}).status_code == 409)
    check("a forward move to a later stage is allowed",
          c.post("/api/cases/case_1/status", headers=hdr(C),
                 json={"status": "evidence_received"}).status_code == 200)
    check("an analyst cannot push a case into compliance review",
          c.post("/api/cases/case_1/status", headers=hdr(A),
                 json={"status": "compliance_review"}).status_code == 409)

    print("\n" + "═" * 62)
    print(f"  {len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("  Failures:")
        for failure in FAILED:
            print(f"    - {failure}")
    print("═" * 62)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
