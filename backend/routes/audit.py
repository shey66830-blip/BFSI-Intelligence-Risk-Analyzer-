"""
Context Guard — Audit Trail Routes

    GET /api/audit-logs   own activity, or every identity's with audit:view_all
"""

from flask import Blueprint, jsonify, request

from middleware import can, current_user, login_required
from services import audit, paging

audit_bp = Blueprint("audit_routes", __name__)


@audit_bp.route("/api/audit-logs", methods=["GET"])
@login_required
def list_audit_logs():
    from config import get_db

    db = get_db()
    user = current_user()

    # Default to the widest trail this identity is entitled to see.
    scope = (request.args.get("scope") or ("all" if can("audit:view_all") else "own")).lower()
    if scope == "all" and not can("audit:view_all"):
        # An analyst asking for the organisation-wide trail is silently narrowed
        # to their own identity rather than handed data they are not entitled to.
        scope = "own"

    limit, offset = paging.window(request.args, default_limit=50, max_limit=500)
    actions = request.args.get("action")
    actions = [actions] if actions and actions != "all" else None

    user_id = user["id"] if scope == "own" else None
    total = db.audit_log.count_documents({"user_id": user_id} if user_id else {})
    entries = audit.query(db, user_id=user_id, actions=actions, limit=limit, offset=offset)

    return jsonify({
        "scope": scope,
        "can_view_all": can("audit:view_all"),
        "entries": entries,
        "pagination": paging.envelope(entries, total, limit, offset),
    })
