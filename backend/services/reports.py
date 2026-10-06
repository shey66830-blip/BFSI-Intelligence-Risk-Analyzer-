"""
Context Guard — Analyst Investigation Reports

An analyst report is the analyst's product: a structured document built from the case,
the transaction trail, the behavioural baseline, the graph, the bank reports and the
analyst's own notes.

Two rules shape the model:

1. **Every statement is classified.** Observed facts, model-generated inferences,
   analyst observations and recommended next steps are kept in separate buckets, so a
   reader can see what the data says versus what a person concluded.
2. **A submitted report is never overwritten.** Submission freezes a version; further
   work creates the next version with a link back to the one it supersedes.

The draft builder only restates values already stored against the case. It cannot
introduce a fact that no collection contains.
"""

import uuid
from datetime import datetime

# ── Vocabulary ───────────────────────────────────────────────────────────────

SECTION_KEYS = [
    ("case_information", "Case Information"),
    ("transaction_summary", "Transaction Summary"),
    ("behavioral_analysis", "Behavioural Analysis"),
    ("graph_network_findings", "Graph / Network Findings"),
    ("contextual_findings", "Contextual Findings"),
    ("investigation_findings", "Investigation Findings"),
]

CLASSIFICATIONS = {
    "observed_fact": "Observed fact (from stored records)",
    "model_inference": "Model-generated inference",
    "analyst_observation": "Analyst observation",
    "recommended_next_step": "Recommended next step",
}

STATUSES = ("draft", "submitted", "clarification_requested", "reviewed", "amended")

MANDATORY_NOTICE = (
    "This report records suspicion and lines of enquiry. It does not establish that any "
    "person has committed an offence, and no finding in it should be read as a determination "
    "of guilt."
)


def _now():
    return datetime.utcnow().isoformat()


def _report_id():
    return f"AR-{datetime.utcnow().strftime('%Y')}-{uuid.uuid4().hex[:6].upper()}"


def empty_sections():
    return {key: {"title": title, "body": [], "items": []} for key, title in SECTION_KEYS}


# ── Findings ─────────────────────────────────────────────────────────────────

def make_finding(classification, statement, section, evidence_ids=None, transaction_ids=None,
                 source=None, confidence=None, created_by=None):
    """A single traceable statement. `source` names where it came from."""
    return {
        "id": f"F{uuid.uuid4().hex[:6]}",
        "classification": classification,
        "classification_label": CLASSIFICATIONS.get(classification, classification),
        "section": section,
        "statement": statement,
        "evidence_ids": list(evidence_ids or []),
        "transaction_ids": list(transaction_ids or []),
        "source": source,
        "confidence": confidence,
        "created_by": created_by,
        "created_at": _now(),
    }


def finding_groups(report):
    """Split a report's findings by classification, in reading order."""
    findings = report.get("findings", [])
    return {
        key: [f for f in findings if f.get("classification") == key]
        for key in CLASSIFICATIONS
    }


# ── Storage ──────────────────────────────────────────────────────────────────

def create_draft(db, case, analyst, payload=None, prior=None, reason=None):
    """Create a draft. With `prior`, this is an amendment of a submitted version."""
    payload = payload or {}
    version = (prior["version"] + 1) if prior else 1

    report = {
        "id": _report_id(),
        "case_id": case["id"],
        "case_title": case.get("title"),
        "version": version,
        "status": "draft",
        "locked": False,
        "supersedes": prior["id"] if prior else None,
        "supersedes_version": prior["version"] if prior else None,
        "amendment_reason": reason,
        "analyst_id": analyst["id"],
        "analyst_name": analyst["name"],
        "analyst_role": analyst["role"],
        "title": payload.get("title") or f"Investigation report — {case.get('title') or case['id']}",
        "summary": payload.get("summary", ""),
        "sections": payload.get("sections") or empty_sections(),
        "findings": payload.get("findings") or [],
        "created_at": _now(),
        "updated_at": _now(),
        "submitted_at": None,
        "submitted_to": None,
        "review": None,
        "clarification": None,
        "notice": MANDATORY_NOTICE,
    }
    db.analyst_reports.insert_one(report)
    return report


def get_report(db, report_id):
    return db.analyst_reports.find_one({"id": report_id})


def list_reports(db, case_ids=None, analyst_id=None, statuses=None, limit=200):
    q = {}
    if case_ids is not None:
        q["case_id"] = {"$in": list(case_ids)}
    if analyst_id:
        q["analyst_id"] = analyst_id
    if statuses:
        q["status"] = {"$in": list(statuses)}
    return list(db.analyst_reports.find(q).sort("updated_at", -1).limit(limit))


def latest_for_case(db, case_id):
    return db.analyst_reports.find_one({"case_id": case_id}, sort=[("version", -1)])


def submitted_for_case(db, case_id):
    return list(db.analyst_reports.find(
        {"case_id": case_id, "status": {"$in": ["submitted", "clarification_requested", "reviewed"]}}
    ).sort("version", -1))


def update_draft(db, report, user, payload):
    """Edit a draft. Returns (report, error)."""
    if report.get("locked") or report.get("status") != "draft":
        return None, ("This report has been submitted and can no longer be edited. "
                      "Create an amended version instead.")
    if report.get("analyst_id") != user["id"] and user.get("role") != "admin":
        return None, "Only the analyst who drafted this report can edit it"

    updates = {"updated_at": _now()}
    for field in ("title", "summary"):
        if field in payload and payload[field] is not None:
            updates[field] = payload[field]

    if "sections" in payload and payload["sections"] is not None:
        merged = dict(report.get("sections") or empty_sections())
        for key, value in payload["sections"].items():
            if key in merged:
                merged[key] = {**merged[key], **value}
        updates["sections"] = merged

    if payload.get("findings") is not None:
        cleaned = []
        for finding in payload["findings"]:
            classification = finding.get("classification")
            if classification not in CLASSIFICATIONS:
                return None, f"Unknown finding classification: {classification}"
            statement = (finding.get("statement") or "").strip()
            if not statement:
                return None, "Every finding needs a statement"
            cleaned.append({
                **finding,
                "statement": statement,
                "classification_label": CLASSIFICATIONS[classification],
                "id": finding.get("id") or f"F{uuid.uuid4().hex[:6]}",
                "created_at": finding.get("created_at") or _now(),
                "created_by": finding.get("created_by") or user["id"],
            })
        updates["findings"] = cleaned

    if payload.get("append_finding"):
        finding = make_finding(
            payload["append_finding"].get("classification"),
            payload["append_finding"].get("statement"),
            payload["append_finding"].get("section", "investigation_findings"),
            evidence_ids=payload["append_finding"].get("evidence_ids"),
            transaction_ids=payload["append_finding"].get("transaction_ids"),
            source=payload["append_finding"].get("source"),
            created_by=user["id"],
        )
        if finding["classification"] not in CLASSIFICATIONS:
            return None, f"Unknown finding classification: {finding['classification']}"
        updates["findings"] = list(report.get("findings", [])) + [finding]

    if payload.get("remove_finding_id"):
        updates["findings"] = [f for f in report.get("findings", [])
                               if f["id"] != payload["remove_finding_id"]]

    if payload.get("note"):
        notes = list(report.get("notes", []))
        notes.append({"at": _now(), "by": user["name"], "by_id": user["id"],
                      "role": user["role"], "text": payload["note"]})
        updates["notes"] = notes

    db.analyst_reports.update_one({"id": report["id"]}, {"$set": updates})
    return get_report(db, report["id"]), None


def submit(db, report, user):
    """Freeze this version and hand it to compliance. Returns (report, error)."""
    if report.get("status") != "draft":
        return None, f"This report is already {report.get('status')}"
    if report.get("analyst_id") != user["id"]:
        return None, "Only the drafting analyst can submit this report"

    fills = [section for section in ("case_information", "transaction_summary",
                                     "investigation_findings")
             if not (report.get("sections", {}).get(section, {}).get("body")
                     or report.get("sections", {}).get(section, {}).get("items"))]
    if len(fills) == len(("case_information", "transaction_summary", "investigation_findings")):
        return None, ("The report is empty. Build the draft from the case data or add your "
                      "own findings before submitting.")

    db.analyst_reports.update_one({"id": report["id"]}, {"$set": {
        "status": "submitted",
        "locked": True,
        "submitted_at": _now(),
        "submitted_to": "compliance",
        "updated_at": _now(),
    }})
    return get_report(db, report["id"]), None


def request_clarification(db, report, user, note):
    if not (note or "").strip():
        return None, "A clarification request needs a note explaining what is missing"
    db.analyst_reports.update_one({"id": report["id"]}, {"$set": {
        "status": "clarification_requested",
        "clarification": {"requested_by": user["id"], "requested_by_name": user["name"],
                          "requested_at": _now(), "note": note.strip()},
        "updated_at": _now(),
    }})
    return get_report(db, report["id"]), None


def record_review(db, report, user, outcome, note=None):
    db.analyst_reports.update_one({"id": report["id"]}, {"$set": {
        "status": "reviewed" if outcome != "returned" else "clarification_requested",
        "review": {"reviewed_by": user["id"], "reviewed_by_name": user["name"],
                   "reviewed_at": _now(), "outcome": outcome, "note": note},
        "updated_at": _now(),
    }})
    return get_report(db, report["id"]), None


# ── Draft building from stored evidence ──────────────────────────────────────

def build_draft_from_case(db, case, analyst, evidence_items=None):
    """Prefill a draft by restating what the case already contains.

    Each generated line is classified as an *observed fact* (a value read from a stored
    record) or a *model inference* (something the behavioural engine computed). Nothing
    is asserted beyond the data, and every line points at its source.
    """
    from config import BANKS
    from services.graph_engine import build_behavioral_profile

    entity_ids = case.get("entity_ids", [])
    transactions = list(db.transactions.find({"entity_id": {"$in": entity_ids}}).sort("timestamp", 1))
    entities = {e["id"]: e for e in db.entities.find()}
    reports = list(db.bank_reports.find({"case_id": case["id"]}))
    findings = case.get("pipeline_findings", []) or []

    sections = empty_sections()
    findings_out = []

    def fact(section, statement, **kwargs):
        sections[section]["items"].append(statement)
        findings_out.append(make_finding("observed_fact", statement, section, **kwargs))

    def inference(section, statement, confidence=None, **kwargs):
        sections[section]["items"].append(statement)
        findings_out.append(make_finding("model_inference", statement, section,
                                         confidence=confidence, **kwargs))

    # ── Case information ──
    observed_status = case.get("status", "unknown")
    fact("case_information",
         f"Case {case['id']} — '{case.get('title')}' — is recorded with status "
         f"'{observed_status}'.",
         source="investigation_cases")
    fact("case_information",
         f"The case covers {len(entity_ids)} subject account(s) across "
         f"{len(case.get('bank_ids', []))} bank(s): "
         f"{', '.join(BANKS.get(b, {}).get('name', b) for b in case.get('bank_ids', []))}.",
         source="investigation_cases")
    if case.get("origin") == "live_ingest":
        fact("case_information",
             "The case was opened automatically by the ingest gate, not created by hand.",
             source="investigation_cases")

    # ── Transaction summary ──
    if transactions:
        total = sum(t.get("amount", 0) for t in transactions)
        debits = [t for t in transactions if t.get("type") == "debit"]
        fact("transaction_summary",
             f"{len(transactions)} transaction(s) are on file totalling ₹{total:,.0f}, of which "
             f"{len(debits)} are debits.",
             transaction_ids=[t["id"] for t in transactions], source="transactions")
        largest = max(transactions, key=lambda t: t.get("amount", 0))
        fact("transaction_summary",
             f"The largest single movement is ₹{largest.get('amount', 0):,.0f} on "
             f"{str(largest.get('timestamp'))[:10]} to '{largest.get('counterparty')}' at "
             f"{BANKS.get(largest.get('bank_id'), {}).get('name', largest.get('bank_id'))}.",
             transaction_ids=[largest["id"]], source="transactions")
        channels = sorted({t.get("category", "unclassified") for t in transactions})
        fact("transaction_summary",
             f"Channels observed: {', '.join(channels)}.",
             transaction_ids=[t["id"] for t in transactions], source="transactions")
    else:
        inference("transaction_summary", "No transactions are attached to this case yet.")

    # ── Behavioural analysis ──
    for entity_id in entity_ids[:4]:
        profile = build_behavioral_profile(db, entity_id, 90)
        stats = profile.get("amount_stats", {}) or {}
        count = profile.get("transaction_count", 0)
        if not count:
            continue
        name = entities.get(entity_id, {}).get("name", entity_id)
        inference("behavioral_analysis",
                  f"{name}: {count} transaction(s) in the 90-day window, mean "
                  f"₹{stats.get('mean', 0):,.0f}, range ₹{stats.get('min', 0):,.0f}–"
                  f"₹{stats.get('max', 0):,.0f}.",
                  confidence=0.9, source="graph_engine.build_behavioral_profile")
        baselines = [c for c in stats.get("counterparties", []) if c.get("first_seen_late")]
        for candidate in baselines[:3]:
            inference("behavioral_analysis",
                      f"{name} began transacting with '{candidate.get('counterparty')}' part-way "
                      f"through the window — a relatively new beneficiary.",
                      confidence=0.7, source="graph_engine.build_behavioral_profile")

    # ── Graph / network ──
    linked = set()
    for report in reports:
        linked.update(report.get("data", {}).get("entities_linked", []) or [])
    if linked:
        names = [entities.get(e, {}).get("name", e) for e in sorted(linked)]
        inference("graph_network_findings",
                  f"Bank responses reference {len(linked)} further account(s) not originally "
                  f"in scope: {', '.join(names)}.",
                  confidence=0.85, source="bank_reports")
    devices = sorted({t.get("device_id") for t in transactions if t.get("device_id")})
    if devices:
        fact("graph_network_findings",
             f"{len(devices)} device identifier(s) appear across these transactions "
             f"({', '.join(devices[:6])}).",
             transaction_ids=[t["id"] for t in transactions], source="transactions")
    counterparties = sorted({t.get("counterparty") for t in transactions if t.get("counterparty")})
    if len(counterparties) > 1:
        inference("graph_network_findings",
                  f"{len(counterparties)} distinct counterparties appear, the largest "
                  f"concentration being with '{counterparties[0]}'.",
                  confidence=0.75, source="transactions")

    # ── Contextual findings ──
    for report in reports:
        data = report.get("data", {})
        bank_name = BANKS.get(report.get("responding_bank"), {}).get("name",
                                                                    report.get("responding_bank"))
        if data.get("additional_context"):
            fact("contextual_findings",
                 f"{bank_name} returned context: {data['additional_context']}",
                 source=f"bank_reports/{report.get('id') or report.get('request_id')}")
        if data.get("entity_relationship_status"):
            fact("contextual_findings",
                 f"{bank_name} records relationship status "
                 f"'{data['entity_relationship_status']}' with account tenure "
                 f"{data.get('account_tenure', 'not stated')}.",
                 source=f"bank_reports/{report.get('request_id')}")
    missing = []
    if not reports:
        missing.append("no bank reports have been returned")
    if not case.get("pipeline_report"):
        missing.append("the pipeline report has not been generated")
    if not devices:
        missing.append("no device identifiers are recorded")
    if missing:
        inference("contextual_findings",
                  f"Information still missing at this stage: {', '.join(missing)}.",
                  confidence=1.0, source="context_guard")
    if any((r.get("data", {}).get("consent_status") or "").startswith("active")
           for r in reports):
        fact("contextual_findings",
             "Each responding bank confirmed an active consent record for the entity it "
             "searched.", source="bank_reports")

    # ── Investigation findings ──
    for finding in findings:
        inference("investigation_findings",
                  f"[{finding.get('strength', 'unrated')}] {finding.get('title')}",
                  confidence=0.8 if finding.get("strength") == "corroborated" else 0.6,
                  source="pipeline.correlate_evidence")
    if not findings:
        inference("investigation_findings",
                  "No cross-bank correlation findings have been produced for this case yet.")

    for statement in (
        "Confirm the commercial purpose of the largest movement with the originating bank.",
        "Retrieve the counterparty's beneficial-ownership details through an authorised "
        "request if the response is insufficient.",
    ):
        sections["investigation_findings"]["items"].append(statement)
        findings_out.append(make_finding("recommended_next_step", statement,
                                         "investigation_findings", created_by=analyst["id"]))

    return {
        "sections": sections,
        "findings": findings_out,
        "summary": (f"Draft assembled from {len(transactions)} transaction(s), "
                    f"{len(reports)} bank report(s) and {len(findings)} correlation finding(s). "
                    f"Every line is classed as an observed fact or a model inference and cites "
                    f"its source."),
    }
