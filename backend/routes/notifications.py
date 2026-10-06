"""
Context Guard — Notifications & Investigation Updates

    GET  /api/notifications                       my notifications
    POST /api/notifications/<id>/read             mark one read
    POST /api/notifications/read-all              mark everything read

    GET  /api/compliance/updates                  cross-case update feed (compliance)
    GET  /api/cases/<case_id>/updates             updates on one case
    POST /api/cases/<case_id>/updates             post an update
    POST /api/updates/<update_id>/acknowledge     acknowledge receipt
"""

from flask import Blueprint, jsonify, request

from config import get_db
from middleware import can, current_user, load_case, login_required, visible_case_ids
from services import audit, paging, updates

notifications_bp = Blueprint("notifications", __name__)


@notifications_bp.route("/api/notifications", methods=["GET"])
@login_required
def list_notifications():
    db = get_db()
    user = current_user()
    unread_only = request.args.get("unread") in ("1", "true", "yes")
    limit, offset = paging.window(request.args)
    items = updates.all_notifications(db, user["id"], unread_only=unread_only,
                                      limit=limit, offset=offset)
    total = updates.notification_count(db, user["id"], unread_only=unread_only)
    return jsonify({
        "notifications": items,
        "unread": updates.unread_count(db, user["id"]),
        "pagination": paging.envelope(items, total, limit, offset),
    })


@notifications_bp.route("/api/notifications/<notification_id>/read", methods=["POST"])
@login_required
def mark_read(notification_id):
    db = get_db()
    user = current_user()
    doc = updates.mark_read(db, notification_id, user["id"])
    if not doc:
        return jsonify({"error": "Notification not found"}), 404
    doc.pop("_id", None)
    return jsonify({"notification": doc, "unread": updates.unread_count(db, user["id"])})


@notifications_bp.route("/api/notifications/read-all", methods=["POST"])
@login_required
def mark_all_read():
    db = get_db()
    user = current_user()
    changed = updates.mark_all_read(db, user["id"])
    return jsonify({"marked": changed, "unread": updates.unread_count(db, user["id"])})


@notifications_bp.route("/api/compliance/updates", methods=["GET"])
@login_required
def compliance_updates():
    """The compliance officer's incoming feed — structured, newest first."""
    db = get_db()
    user = current_user()
    if not can("reports:review"):
        audit.record(db, user, "access_denied", target="compliance_updates",
                     detail="Missing permission reports:review", resource_type="investigation_update",
                     result="denied", reason="requires reports:review")
        return jsonify({"error": "Your role cannot open the investigation update feed",
                        "code": "forbidden", "required_permission": "reports:review"}), 403

    acknowledged = request.args.get("acknowledged")
    acknowledged = None if acknowledged in (None, "all") else acknowledged == "true"
    case_id = request.args.get("case_id")
    case_ids = [case_id] if case_id else visible_case_ids(db, user)

    items = updates.list_updates(db, case_ids=case_ids, acknowledged=acknowledged,
                                 limit=int(request.args.get("limit", 100)))
    types = {}
    for item in items:
        types[item["type"]] = types.get(item["type"], 0) + 1

    return jsonify({
        "updates": items,
        "unacknowledged": updates.unacknowledged_count(db, case_ids),
        "by_type": types,
        "update_types": [{"key": k, "label": v["label"]} for k, v in updates.UPDATE_TYPES.items()],
        "can_acknowledge": can("updates:acknowledge"),
    })


@notifications_bp.route("/api/cases/<case_id>/updates", methods=["GET"])
@login_required
def case_updates(case_id):
    db = get_db()
    _, error = load_case(case_id)
    if error:
        return jsonify(error[0]), error[1]

    items = updates.list_updates(db, case_ids=[case_id], limit=100)
    return jsonify({
        "case_id": case_id,
        "updates": items,
        "unacknowledged": updates.unacknowledged_count(db, [case_id]),
        "can_acknowledge": can("updates:acknowledge"),
        "can_post": can("updates:post"),
    })


@notifications_bp.route("/api/cases/<case_id>/updates", methods=["POST"])
@login_required
def post_update(case_id):
    db = get_db()
    user = current_user()
    case, error = load_case(case_id, permission="updates:post")
    if error:
        return jsonify(error[0]), error[1]

    payload = request.json or {}
    if not (payload.get("title") or "").strip():
        return jsonify({"error": "An update needs a title"}), 400

    update = updates.post(db, case, user, payload.get("type", "finding"),
                          payload["title"].strip(), (payload.get("description") or "").strip(),
                          metadata=payload.get("metadata") or {})
    audit.record(db, user, "update_posted", target=update["id"], case_id=case_id,
                 resource_type="investigation_update", resource_id=update["id"],
                 detail=f"Posted update: {update['title']}")
    return jsonify({"update": update}), 201


@notifications_bp.route("/api/updates/<update_id>/acknowledge", methods=["POST"])
@login_required
def acknowledge_update(update_id):
    db = get_db()
    user = current_user()
    update = db.investigation_updates.find_one({"id": update_id})
    if not update:
        return jsonify({"error": "Update not found"}), 404
    _, error = load_case(update["case_id"], permission="updates:acknowledge")
    if error:
        return jsonify(error[0]), error[1]

    acknowledged = updates.acknowledge(db, update, user, (request.json or {}).get("note"))
    audit.record(db, user, "update_acknowledged", target=update_id, case_id=update["case_id"],
                 resource_type="investigation_update", resource_id=update_id,
                 detail=f"Acknowledged: {update.get('title')}")
    acknowledged.pop("_id", None)
    return jsonify({"update": acknowledged})
