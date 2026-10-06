"""
Context Guard — Cases Routes

Flask blueprint for case management and transaction queries.
Every route is authenticated; case and field visibility depends on the caller's role.
"""

from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from config import BANKS, get_db
from middleware import case_access, current_user, load_case, login_required, visible_case_ids
from models import (
    get_all_cases, get_all_entities, get_all_transactions, get_case,
    get_decision_by_case, get_entity, get_reports_by_case,
    get_transactions_by_case, serialize_doc,
)
from services import access as access_service, audit, evidence, notes as note_service, privacy, reports as report_service, updates, workflow
from services import paging
from services import workqueue
from services.settings import get_settings

cases_bp = Blueprint("cases", __name__)


def _scoped_cases(db, user):
    """Case documents this identity is allowed to see, already serialised."""
    cases = serialize_doc(get_all_cases(db))
    allowed = visible_case_ids(db, user)
    if allowed is None:
        return cases, None
    return [c for c in cases if c.get("id") in allowed], set(allowed)


def _known_names(db):
    """Entity names used to scrub free-text case fields for masked viewers."""
    return [e.get("name") for e in db.entities.find({}, {"name": 1}) if e.get("name")]


def _scoped_entity_ids(db, user):
    """Entity ids reachable from the cases this identity can see."""
    if visible_case_ids(db, user) is None:
        return None
    ids = set()
    for case in db.cases.find({"assigned_to": user["id"]}, {"entity_ids": 1}):
        ids.update(case.get("entity_ids", []))
    return ids


@cases_bp.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Context Guard", "storage": "MongoDB"})


@cases_bp.route("/api/cases", methods=["GET"])
@login_required
def list_cases():
    """Return every case the caller may see, with summary info."""
    db = get_db()
    user = current_user()
    level = privacy.redaction_level(user, get_settings(db))

    cases, _ = _scoped_cases(db, user)
    cases = privacy.mask_cases(cases, level, _known_names(db))
    limit, offset = paging.window(request.args)
    page, total = paging.slice_page(cases, limit, offset)
    cases = page

    for case in cases:
        entity_ids = case.get("entity_ids", [])
        txns = list(db.transactions.find({"entity_id": {"$in": entity_ids}}))
        case["transaction_count"] = len(txns)
        case["total_volume"] = sum(t.get("amount", 0) for t in txns)
        case["bank_names"] = [BANKS.get(b, {}).get("name", b) for b in case.get("bank_ids", [])]
        case["assigned_to"] = case.get("assigned_to")
        case["assigned_to_name"] = case.get("assigned_to_name")

    return jsonify(cases), 200, paging.page_headers(total, limit, offset, len(cases))


@cases_bp.route("/api/cases/<case_id>", methods=["GET"])
@login_required
def get_case_detail(case_id):
    """Return full case details — if this identity is entitled to this case."""
    db = get_db()
    user = current_user()

    case = get_case(db, case_id)
    if not case:
        return jsonify({"error": "Case not found"}), 404

    allowed, reason = case_access(case, user)
    if not allowed:
        audit.record(db, user, "access_denied", target=case_id, detail=reason)
        return jsonify({"error": reason, "code": "forbidden"}), 403

    level = privacy.redaction_level(user, get_settings(db))

    case = serialize_doc(case)
    if level == "masked":
        names = _known_names(db)
        case["title"] = privacy.redact_text(case.get("title"), names)
        case["description"] = privacy.redact_text(case.get("description"), names)

    entity_ids = case.get("entity_ids", [])
    transactions = serialize_doc(
        list(db.transactions.find({"entity_id": {"$in": entity_ids}}).sort("timestamp", 1))
    )

    for t in transactions:
        entity = get_entity(db, t.get("entity_id"))
        t["entity_name"] = entity.get("name", "Unknown") if entity else "Unknown"
        t["bank_name"] = BANKS.get(t.get("bank_id"), {}).get("name", "Unknown")
        # Descriptions are prose and can carry a name the structured fields hide.
        t["description"] = privacy.redact_text(t.get("description"), _known_names(db))

    transactions = [privacy.mask_transaction(t, level) for t in transactions]

    case["transactions"] = transactions
    case["reports"] = serialize_doc(get_reports_by_case(db, case_id))
    case["decision"] = serialize_doc(get_decision_by_case(db, case_id))
    case["bank_names"] = [BANKS.get(b, {}).get("name", b) for b in case.get("bank_ids", [])]
    case["assigned_to_name"] = privacy.mask_name(case.get("assigned_to_name")) if level == "masked" else case.get("assigned_to_name")
    case["privacy"] = {
        "level": level,
        "redacted_fields": sorted({f for t in transactions for f in t.get("redacted_fields", [])}),
        "note": ("Identifiers masked for your role. Compliance and administrators see unmasked values."
                 if level == "masked" else "Full identifiers visible for your role."),
    }

    # Workflow position, next moves available to this role, and what the case holds.
    from middleware import can
    can_change = can("cases:status_change")
    status = case.get("status")
    case["workflow"] = {
        "status": status,
        "label": workflow.label_for(status),
        "progress": workflow.progress(status),
        "next_states": [{"key": k, "label": workflow.label_for(k)}
                        for k in workflow.next_states(status, user.get("role"))]
        if can_change else [],
        "stages": workflow.STAGES,
    }
    case["evidence"] = {
        "count": db.case_evidence.count_documents({"case_id": case_id}),
        "restricted_category_count": len(access_service.vector(db, case_id)["available"]),
        "authorization_state": ("authorized" if access_service.active_authorization(db, user["id"], case_id)
                                else ("expired" if access_service.expired_authorization(db, user["id"], case_id)
                                      else "locked")),
    }
    case["updates"] = {
        "total": db.investigation_updates.count_documents({"case_id": case_id}),
        "unacknowledged": updates.unacknowledged_count(db, [case_id]),
    }
    # The analyst's working record, so the case header can badge it without a second call.
    case["notes"] = note_service.note_counts(db, case_id)
    case["relevance"] = {
        "marked": note_service.marked_count(db, case_id),
        "transaction_ids": sorted(
            r["transaction_id"]
            for r in note_service.list_relevance(db, case_id, relevant_only=True)
        ),
    }
    case["analyst_reports"] = [
        {"id": r["id"], "version": r["version"], "status": r["status"],
         "analyst_name": r.get("analyst_name"), "submitted_at": r.get("submitted_at"),
         "updated_at": r.get("updated_at")}
        for r in db.analyst_reports.find({"case_id": case_id}).sort("version", -1)
    ]
    case["access_requests"] = [
        {"id": r["id"], "status": r["status"], "categories": r.get("categories"),
         "created_at": r.get("created_at"), "expires_at": r.get("expires_at")}
        for r in db.access_requests.find({"case_id": case_id, "requested_by": user["id"]})
    ]

    audit.record(db, user, "case_opened", target=case_id, case_id=case_id,
                 resource_type="investigation_case", resource_id=case_id,
                 detail=f"Opened the case ({level} identifiers)")
    if transactions:
        audit.record(db, user, "transaction_viewed", target=case_id, case_id=case_id,
                     resource_type="transaction",
                     detail=f"Reviewed {len(transactions)} transaction(s) on this case")

    return jsonify(case)


@cases_bp.route("/api/cases/<case_id>/status", methods=["POST"])
@login_required
def change_status(case_id):
    """Move a case along the lifecycle, subject to the workflow rules for the role."""
    db = get_db()
    user = current_user()
    case, error = load_case(case_id, permission="cases:status_change")
    if error:
        return jsonify(error[0]), error[1]

    payload = request.json or {}
    target = payload.get("status")
    if not target:
        return jsonify({"error": "status is required"}), 400

    allowed, reason = workflow.can_transition(case.get("status"), target, user.get("role"))
    if not allowed:
        audit.record(db, user, "status_changed", target=case_id, case_id=case_id,
                     resource_type="investigation_case", resource_id=case_id,
                     result="denied", reason=reason)
        return jsonify({"error": reason, "code": "invalid_transition"}), 409

    previous = case.get("status")
    db.cases.update_one({"id": case_id}, {"$set": {"status": target}})
    audit.record(db, user, "status_changed", target=case_id, case_id=case_id,
                 resource_type="investigation_case", resource_id=case_id,
                 detail=f"{workflow.label_for(previous)} → {workflow.label_for(target)}",
                 reason=payload.get("reason"))
    updates.post(db, case, user, "status_change",
                 title=f"Status changed to {workflow.label_for(target)}",
                 description=payload.get("reason") or f"Moved by {user['name']}",
                 metadata={"from": previous, "to": target})

    return jsonify({
        "case_id": case_id,
        "status": target,
        "label": workflow.label_for(target),
        "previous": previous,
        "next_states": [{"key": k, "label": workflow.label_for(k)}
                        for k in workflow.next_states(target, user.get("role"))],
    })


@cases_bp.route("/api/transactions", methods=["GET"])
@login_required
def list_transactions():
    """Return transactions, scoped to the caller's visible cases."""
    db = get_db()
    user = current_user()
    level = privacy.redaction_level(user, get_settings(db))

    entity_ids = _scoped_entity_ids(db, user)
    flt = {}
    if entity_ids is not None:
        flt["entity_id"] = {"$in": list(entity_ids)}

    case_id = request.args.get("case_id")
    if case_id:
        case = get_case(db, case_id)
        if not case:
            return jsonify({"error": "Case not found"}), 404
        allowed, reason = case_access(case, user)
        if not allowed:
            return jsonify({"error": reason, "code": "forbidden"}), 403
        txns = get_transactions_by_case(db, case_id)
    else:
        txns = list(db.transactions.find(flt).sort("timestamp", 1))

    txns = serialize_doc(txns)
    names = _known_names(db)
    for t in txns:
        entity = get_entity(db, t.get("entity_id"))
        t["entity_name"] = entity.get("name", "Unknown") if entity else "Unknown"
        t["bank_name"] = BANKS.get(t.get("bank_id"), {}).get("name", "Unknown")
        t["description"] = privacy.redact_text(t.get("description"), names)
        t["counterparty"] = privacy.redact_text(t.get("counterparty"), names)

    limit, offset = paging.window(request.args)
    page, total = paging.slice_page(txns, limit, offset)
    return (jsonify([privacy.mask_transaction(t, level) for t in page]), 200,
            paging.page_headers(total, limit, offset, len(page)))


@cases_bp.route("/api/entities", methods=["GET"])
@login_required
def list_entities():
    db = get_db()
    user = current_user()
    level = privacy.redaction_level(user, get_settings(db))

    entities = serialize_doc(get_all_entities(db))
    entity_ids = _scoped_entity_ids(db, user)
    if entity_ids is not None:
        entities = [e for e in entities if e.get("id") in entity_ids]

    if level == "masked":
        for e in entities:
            e["name"] = privacy.mask_name(e.get("name"))
            e["redacted_fields"] = ["name"]

    return jsonify(entities)


@cases_bp.route("/api/banks", methods=["GET"])
@login_required
def list_banks():
    return jsonify(list(BANKS.values()))


def _movement(cases, txns):
    """Period-over-period deltas and a daily activity series for the overview.

    Both are computed from the same scope-filtered documents the caller can already
    count, so a chip can never show movement the caller could not see themselves.
    """
    now = datetime.utcnow()
    week = timedelta(days=7)

    def _parsed(value):
        try:
            return datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None

    def _delta(current, previous):
        pct = None if not previous else round((current - previous) * 100.0 / previous, 1)
        return {"current": current, "previous": previous, "pct": pct}

    def _count(items, key):
        current = previous = 0
        for item in items:
            stamp = _parsed(item.get(key))
            if stamp is None or stamp > now:
                continue
            if stamp > now - week:
                current += 1
            elif stamp > now - 2 * week:
                previous += 1
        return current, previous

    case_now, case_before = _count(cases, "created_at")

    txn_now = txn_before = 0
    volume_now = volume_before = 0.0
    for txn in txns:
        stamp = _parsed(txn.get("timestamp"))
        if stamp is None or stamp > now:
            continue
        amount = txn.get("amount", 0) or 0
        if stamp > now - week:
            txn_now += 1
            volume_now += amount
        elif stamp > now - 2 * week:
            txn_before += 1
            volume_before += amount

    # Daily buckets for the activity chart: oldest first, ending on the current day.
    buckets = {}
    for offset in range(29, -1, -1):
        key = (now - timedelta(days=offset)).date().isoformat()
        buckets[key] = {"date": key, "transactions": 0, "volume": 0.0}
    for txn in txns:
        stamp = _parsed(txn.get("timestamp"))
        if stamp is None:
            continue
        bucket = buckets.get(stamp.date().isoformat())
        if bucket is not None:
            bucket["transactions"] += 1
            bucket["volume"] = round(bucket["volume"] + (txn.get("amount", 0) or 0), 2)

    return {
        "deltas": {
            "cases": _delta(case_now, case_before),
            "transactions": _delta(txn_now, txn_before),
            "volume": _delta(round(volume_now, 2), round(volume_before, 2)),
        },
        "activity": list(buckets.values()),
    }


@cases_bp.route("/api/dashboard-stats", methods=["GET"])
@login_required
def dashboard_stats():
    """Counts that respect the caller's case visibility."""
    db = get_db()
    user = current_user()

    cases, allowed = _scoped_cases(db, user)
    if allowed is None:
        all_txns = serialize_doc(get_all_transactions(db))
        entity_count = db.entities.count_documents({})
    else:
        entity_ids = _scoped_entity_ids(db, user) or set()
        all_txns = serialize_doc(list(db.transactions.find({"entity_id": {"$in": list(entity_ids)}})))
        entity_count = len(entity_ids)

    by_status = {}
    for case in cases:
        by_status[case.get("status", "unknown")] = by_status.get(case.get("status", "unknown"), 0) + 1

    # What is on this role's desk right now, computed from the same collections the
    # rest of the application writes to.
    case_ids = None if allowed is None else [c["id"] for c in cases]
    work_queue = workqueue.build(db, user, case_ids, cases)

    movement = _movement(cases, all_txns)

    return jsonify({
        "work_queue": work_queue,
        "total_cases": len(cases),
        "total_transactions": len(all_txns),
        "total_volume": round(sum(t.get("amount", 0) for t in all_txns), 2),
        "banks_connected": len(BANKS),
        "entities_monitored": entity_count,
        "cases_by_status": by_status,
        "scope": "all" if allowed is None else "assigned",
        "viewer": user.get("name"),
        "deltas": movement["deltas"],
        "activity": movement["activity"],
    })
