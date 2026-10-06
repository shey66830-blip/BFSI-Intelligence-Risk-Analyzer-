"""
Context Guard — Evidence Vault Routes

    GET    /api/cases/<case_id>/evidence        vault contents + folder summary
    POST   /api/cases/<case_id>/evidence        file a new item
    POST   /api/cases/<case_id>/evidence/baseline  file the case's stored evidence
    GET    /api/evidence/<evidence_id>          a single item
    PATCH  /api/evidence/<evidence_id>          organise (folder / status / access level)
    POST   /api/evidence/<evidence_id>/supersede   corrected version (nothing is overwritten)
    GET    /api/cases/<case_id>/timeline        reconstructed sequence of events
"""

from flask import Blueprint, jsonify, request

from config import BANKS, get_db
from middleware import can, current_user, load_case, login_required
from services import access as access_service, audit, evidence as vault, paging, updates

evidence_bp = Blueprint("evidence", __name__)


def _vault_visibility(user):
    """(include_compliance_only, include_restricted_content) for this caller."""
    include_compliance = user.get("role") in ("compliance", "admin")
    return include_compliance, False


@evidence_bp.route("/api/cases/<case_id>/evidence", methods=["GET"])
@login_required
def list_evidence(case_id):
    db = get_db()
    user = current_user()
    case, error = load_case(case_id)
    if error:
        return jsonify(error[0]), error[1]

    include_compliance, _ = _vault_visibility(user)
    authorization = access_service.active_authorization(db, user["id"], case_id)

    # A case that has never been opened in the vault gets its stored evidence filed,
    # so the analyst starts from what the system already knows.
    if db.case_evidence.count_documents({"case_id": case_id}) == 0:
        filed = vault.file_case_baseline(db, case)
        if filed:
            audit.record(db, None, "system", target=case_id, case_id=case_id,
                         resource_type="case_evidence",
                         detail=f"Filed {len(filed)} existing record(s) into the vault",
                         system=True)

    all_items = vault.list_items(db, case_id, include_compliance=include_compliance,
                                 include_restricted=bool(authorization))
    # The summary always describes the whole vault; the item list is a page of it.
    limit, offset = paging.window(request.args)
    items, total = paging.slice_page(all_items, limit, offset)
    summary = vault.vault_summary(db, case_id, include_compliance=include_compliance)
    requests = access_service.list_requests(db, requester_id=user["id"], case_ids=[case_id])

    audit.record(db, user, "evidence_accessed", target=case_id, case_id=case_id,
                 resource_type="case_evidence",
                 detail=f"Opened the evidence vault ({total} item(s))"
                        + (" with an active authorisation" if authorization else ""))

    return jsonify({
        "case_id": case_id,
        "items": items,
        "summary": summary,
        "pagination": paging.envelope(items, total, limit, offset),
        "can_add": can("evidence:add"),
        "can_manage": can("evidence:manage"),
        "authorization": authorization,
        "authorization_state": ("authorized" if authorization else
                                ("expired" if access_service.expired_authorization(db, user["id"], case_id)
                                 else "locked")),
        "access_requests": requests,
        "folders": [{"key": k, "label": l, "description": d} for k, l, d in vault.FOLDERS],
    })


@evidence_bp.route("/api/cases/<case_id>/evidence", methods=["POST"])
@login_required
def add_evidence(case_id):
    db = get_db()
    user = current_user()
    case, error = load_case(case_id, permission="evidence:add")
    if error:
        return jsonify(error[0]), error[1]

    payload = request.json or {}
    # Analysts may not file something as restricted or compliance-only.
    if user["role"] == "analyst" and payload.get("access_level") in ("restricted", "compliance_only"):
        return jsonify({"error": "Only compliance officers or administrators can restrict evidence",
                        "code": "forbidden"}), 403

    item, message = vault.add(db, case, user, payload)
    if message:
        return jsonify({"error": message}), 400

    audit.record(db, user, "evidence_added", target=item["id"], case_id=case_id,
                 resource_type="case_evidence", resource_id=item["id"],
                 detail=f"Filed '{item['title']}' in {item['folder']} ({item['access_level']})")
    updates.post(db, case, user, "evidence_added", title=f"Evidence added: {item['title']}",
                 description=item.get("description") or item["folder"],
                 metadata={"evidence_id": item["id"], "folder": item["folder"]})
    return jsonify({"item": {k: v for k, v in item.items() if k != "_id"}}), 201


@evidence_bp.route("/api/cases/<case_id>/evidence/baseline", methods=["POST"])
@login_required
def file_baseline(case_id):
    db = get_db()
    user = current_user()
    case, error = load_case(case_id, permission="evidence:add")
    if error:
        return jsonify(error[0]), error[1]

    filed = vault.file_case_baseline(db, case)
    audit.record(db, user, "evidence_added", target=case_id, case_id=case_id,
                 resource_type="case_evidence",
                 detail=f"Filed {len(filed)} stored record(s) into the vault")
    return jsonify({"filed": len(filed),
                    "items": vault.list_items(db, case_id, include_compliance=True)})


@evidence_bp.route("/api/evidence/<evidence_id>", methods=["GET"])
@login_required
def read_evidence(evidence_id):
    db = get_db()
    user = current_user()
    item = vault.get(db, evidence_id)
    if not item:
        return jsonify({"error": "Evidence not found"}), 404
    case, error = load_case(item["case_id"])
    if error:
        return jsonify(error[0]), error[1]

    level = item.get("access_level", "case")
    if level == "compliance_only" and user.get("role") not in ("compliance", "admin"):
        audit.record(db, user, "access_denied", target=evidence_id, case_id=item["case_id"],
                     resource_type="case_evidence", resource_id=evidence_id,
                     result="denied", reason="compliance-only evidence")
        return jsonify({"error": "This evidence item is restricted to compliance officers",
                        "code": "forbidden"}), 403
    if level == "restricted":
        allowed, auth, reason = access_service.restricted_access(db, user, item["case_id"])
        if not allowed:
            audit.record(db, user, "restricted_denied", target=evidence_id,
                         case_id=item["case_id"], resource_type="case_evidence",
                         resource_id=evidence_id, result="denied", reason=reason)
            return jsonify({"error": reason, "code": "restricted", "locked": True}), 403
        item["authorization"] = auth

    audit.record(db, user, "evidence_accessed", target=evidence_id, case_id=item["case_id"],
                 resource_type="case_evidence", resource_id=evidence_id,
                 detail=f"Read '{item.get('title')}'")
    item.pop("_id", None)
    return jsonify({"item": item})


@evidence_bp.route("/api/evidence/<evidence_id>/provenance", methods=["GET"])
@login_required
def evidence_provenance(evidence_id):
    """Where this record came from and who put it there, in full.

    Provenance is what lets a reviewer accept a finding without re-deriving it: which
    request produced it, under which authorisation, filed by whom, and what it
    supersedes. It is read under the same gate as the record itself.
    """
    db = get_db()
    user = current_user()
    item = vault.get(db, evidence_id)
    if not item:
        return jsonify({"error": "Evidence not found"}), 404
    _, error = load_case(item["case_id"])
    if error:
        return jsonify(error[0]), error[1]

    level = item.get("access_level", "case")
    if level == "compliance_only" and user.get("role") not in ("compliance", "admin"):
        audit.record(db, user, "access_denied", target=evidence_id, case_id=item["case_id"],
                     resource_type="case_evidence", resource_id=evidence_id,
                     result="denied", reason="provenance of compliance-only evidence")
        return jsonify({"error": "This evidence item is restricted to compliance officers",
                        "code": "forbidden"}), 403
    if level == "restricted":
        allowed, _, reason = access_service.restricted_access(db, user, item["case_id"])
        if not allowed:
            audit.record(db, user, "restricted_denied", target=evidence_id,
                         case_id=item["case_id"], resource_type="case_evidence",
                         resource_id=evidence_id, result="denied", reason=reason)
            return jsonify({"error": reason, "code": "restricted", "locked": True}), 403

    audit.record(db, user, "view", target=evidence_id, case_id=item["case_id"],
                 resource_type="case_evidence", resource_id=evidence_id,
                 detail=f"Read the provenance of '{item.get('title')}'")
    payload = vault.lineage(db, item)
    payload.pop("_id", None)
    return jsonify(payload)


@evidence_bp.route("/api/evidence/<evidence_id>", methods=["PATCH"])
@login_required
def organise_evidence(evidence_id):
    db = get_db()
    user = current_user()
    item = vault.get(db, evidence_id)
    if not item:
        return jsonify({"error": "Evidence not found"}), 404
    case, error = load_case(item["case_id"], permission="evidence:manage")
    if error:
        return jsonify(error[0]), error[1]

    updated, message = vault.update_metadata(db, item, user, request.json or {})
    if message:
        return jsonify({"error": message}), 400

    audit.record(db, user, "evidence_updated", target=evidence_id, case_id=item["case_id"],
                 resource_type="case_evidence", resource_id=evidence_id,
                 detail=f"Reorganised: {', '.join(k for k in (request.json or {}) if k != 'note')}")
    return jsonify({"item": {k: v for k, v in updated.items() if k != "_id"}})


@evidence_bp.route("/api/evidence/<evidence_id>/supersede", methods=["POST"])
@login_required
def supersede_evidence(evidence_id):
    db = get_db()
    user = current_user()
    item = vault.get(db, evidence_id)
    if not item:
        return jsonify({"error": "Evidence not found"}), 404
    case, error = load_case(item["case_id"], permission="evidence:add")
    if error:
        return jsonify(error[0]), error[1]

    replacement, message = vault.supersede(db, item, user, request.json or {})
    if message:
        return jsonify({"error": message}), 409

    audit.record(db, user, "evidence_added", target=replacement["id"], case_id=item["case_id"],
                 resource_type="case_evidence", resource_id=replacement["id"],
                 detail=f"Filed version {replacement.get('version')} superseding {item['id']}")
    return jsonify({"item": {k: v for k, v in replacement.items() if k != "_id"}})


@evidence_bp.route("/api/cases/<case_id>/timeline", methods=["GET"])
@login_required
def case_timeline(case_id):
    """Reconstruct the case sequence from the records that exist, newest first."""
    db = get_db()
    user = current_user()
    case, error = load_case(case_id)
    if error:
        return jsonify(error[0]), error[1]

    events = []

    def add(at, kind, title, detail=None, actor=None, ref=None):
        if not at:
            return
        events.append({"at": str(at), "kind": kind, "title": title, "detail": detail,
                       "actor": actor, "ref": ref})

    add(case.get("created_at"), "case", f"Case opened — {case.get('title')}",
        f"Score {round((case.get('score') or 0) * 100)}%", "Context Guard", case["id"])

    for txn in db.transactions.find({"entity_id": {"$in": case.get("entity_ids", [])}}):
        add(txn.get("timestamp"), "transaction",
            f"{str(txn.get('type', '')).title()} ₹{txn.get('amount', 0):,.0f} — {txn.get('description')}",
            f"{txn.get('counterparty')} · {BANKS.get(txn.get('bank_id'), {}).get('name', txn.get('bank_id'))}",
            txn.get("entity_id"), txn["id"])

    for report in db.bank_reports.find({"case_id": case_id}):
        add(report.get("created_at") or report.get("timestamp"), "bank_report",
            f"{report.get('responding_bank_name') or report.get('responding_bank')} responded",
            report.get("data", {}).get("additional_context") or report.get("status"),
            report.get("responding_bank"), report.get("request_id"))

    for stage in case.get("pipeline_trace", []) or []:
        if stage.get("status") in ("done", "skipped"):
            add(case.get("updated_at"), "pipeline",
                f"{stage.get('order')}. {stage.get('title')}", stage.get("summary"),
                stage.get("actor"), stage.get("key"))

    for report in db.analyst_reports.find({"case_id": case_id}):
        add(report.get("created_at"), "analyst_report",
            f"Analyst report v{report.get('version')} drafted by {report.get('analyst_name')}",
            report.get("summary"), report.get("analyst_name"), report["id"])
        add(report.get("submitted_at"), "analyst_report",
            f"Analyst report v{report.get('version')} submitted to compliance",
            report.get("summary"), report.get("analyst_name"), report["id"])

    for item in vault.list_items(db, case_id, include_compliance=user.get("role") in ("compliance", "admin"),
                                 include_restricted=False):
        add(item.get("created_at"), "evidence", f"Evidence filed — {item.get('title')}",
            item.get("folder"), item.get("created_by_name"), item["id"])

    for update in updates.list_updates(db, case_ids=[case_id], limit=100):
        add(update.get("created_at"), "update", update.get("title"),
            update.get("description"), update.get("submitted_by_name"), update["id"])

    for request in db.access_requests.find({"case_id": case_id}):
        add(request.get("created_at"), "access_request",
            f"Restricted access requested ({request.get('id')})",
            ", ".join(request.get("category_labels") or []), request.get("requested_by_name"),
            request.get("id"))
        if request.get("decision"):
            add(request["decision"].get("at"),
                "access_decision",
                f"Access request {request.get('status')} by {request['decision'].get('by_name')}",
                request["decision"].get("reason") or request["decision"].get("note"),
                request["decision"].get("by_name"), request.get("id"))

    for entry in audit.query(db, case_id=case_id, limit=120):
        add(entry.get("timestamp"), "audit", f"{entry.get('action_label') or entry.get('action')}",
            entry.get("detail"), entry.get("user"), entry.get("id"))

    events.sort(key=lambda e: e["at"], reverse=True)

    audit.record(db, user, "view", target=case_id, case_id=case_id,
                 resource_type="timeline", detail="Viewed the case timeline")
    return jsonify({"case_id": case_id, "events": events, "count": len(events)})
