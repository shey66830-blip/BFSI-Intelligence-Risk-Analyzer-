"""
Context Guard — Administration Routes

    GET    /api/users                list accounts            (users:manage)
    POST   /api/users                create an account        (users:manage)
    PATCH  /api/users/<user_id>      role / status / password (users:manage)
    POST   /api/cases/<case_id>/assign  assign a case owner  (cases:assign)
    GET    /api/settings             org settings             (authenticated)
    PUT    /api/settings             update org settings      (settings:manage)
"""

from flask import Blueprint, jsonify, request

from config import ORGANIZATION
from middleware import current_user, login_required, requires_permission
from services import access as access_service, audit, backtest, paging
from services.settings import get_settings, update_settings
from services.users import (
    ADMIN_DOES_NOT_IMPLY, ROLE_META, ROLE_PERMISSIONS, assign_case, create_user,
    get_user_by_id, list_users, public_user, update_user,
)

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/api/users", methods=["GET"])
@admin_bp.route("/api/admin/users", methods=["GET"])
@requires_permission("users:manage")
def get_users():
    from config import get_db

    db = get_db()
    users = list_users(db)
    payload = []
    for user in users:
        item = public_user(user)
        # Surface each analyst's live case load for the management table.
        case_ids = [c["id"] for c in db.cases.find({"assigned_to": user["id"]}, {"id": 1})]
        item["active_case_count"] = len(case_ids)
        item["open_assignments"] = case_ids
        item["unread_notifications"] = db.notifications.count_documents(
            {"user_id": user["id"], "read_at": None})
        payload.append(item)

    return jsonify({
        "users": payload,
        "roles": [
            {
                "value": key,
                "label": meta["label"],
                "code": meta["code"],
                "description": meta["description"],
                "responsibility": meta.get("responsibility"),
                "permissions": sorted(ROLE_PERMISSIONS[key]),
                "holders": sum(1 for u in users if u.get("role") == key),
            }
            for key, meta in ROLE_META.items()
        ],
        "organization": ORGANIZATION,
        "policy_notes": ADMIN_DOES_NOT_IMPLY,
    })


@admin_bp.route("/api/users/analysts", methods=["GET"])
@requires_permission("cases:assign")
def list_analysts():
    """Minimal analyst roster for case assignment (compliance + admin only)."""
    from config import get_db

    db = get_db()
    roster = []
    for user in db.users.find({"role": "analyst", "status": "active"}).sort("name", 1):
        roster.append({
            "id": user["id"],
            "name": user["name"],
            "username": user["username"],
            "active_case_count": db.cases.count_documents({"assigned_to": user["id"]}),
        })
    return jsonify({"analysts": roster})


@admin_bp.route("/api/users", methods=["POST"])
@requires_permission("users:manage")
def add_user():
    from config import get_db

    db = get_db()
    actor = current_user()
    user, error = create_user(db, request.json or {})
    if error:
        return jsonify({"error": error}), 400

    audit.record(db, actor, "action", target=user["username"],
                 detail=f"Created {user['role']} account for {user['name']}",
                 metadata={"role": user["role"]})
    return jsonify({"user": public_user(user)}), 201


@admin_bp.route("/api/users/<user_id>", methods=["PATCH"])
@requires_permission("users:manage")
def edit_user(user_id):
    from config import get_db

    db = get_db()
    actor = current_user()
    if user_id == actor["id"] and (request.json or {}).get("status") == "suspended":
        return jsonify({"error": "You cannot suspend your own account"}), 400

    target = get_user_by_id(db, user_id)
    if not target:
        return jsonify({"error": "User not found"}), 404

    user, error = update_user(db, user_id, request.json or {})
    if error:
        return jsonify({"error": error}), 400

    labels = {
        "role": "role", "status": "status", "name": "name", "email": "email",
        "title": "title", "assigned_case_ids": "case assignments", "password": "password",
    }
    changed = ", ".join(labels[k] for k in (request.json or {}) if k in labels)
    audit.record(db, actor, "action", target=user["username"],
                 detail=f"Updated {changed or 'account'}",
                 metadata={"role": user["role"], "status": user["status"]})
    return jsonify({"user": public_user(user)})


@admin_bp.route("/api/cases/<case_id>/assign", methods=["POST"])
@requires_permission("cases:assign")
def assign(case_id):
    from config import get_db

    db = get_db()
    actor = current_user()
    user_id = (request.json or {}).get("user_id")

    case, error = assign_case(db, case_id, user_id, assigned_by=actor["id"])
    if error:
        return jsonify({"error": error}), 400

    if user_id:
        assignee = get_user_by_id(db, user_id)
        detail = f"Assigned to {assignee['name']}"
    else:
        detail = "Assignment cleared"
    audit.record(db, actor, "action", target=case_id, detail=detail)

    return jsonify({"case_id": case_id, "assigned_to": case.get("assigned_to"),
                    "assigned_to_name": case.get("assigned_to_name")})


@admin_bp.route("/api/admin/audit-logs", methods=["GET"])
@requires_permission("users:manage")
def admin_audit_logs():
    """Administrator console view of the audit trail, filterable by user and case."""
    from config import get_db

    db = get_db()
    action = request.args.get("action")
    # A read-only window on an append-only log. The page size is generous because the
    # console is meant to show an investigation's history, not a feed — but it is still
    # a page, and the caller is told the size of the log it is a page of.
    limit, offset = paging.window(request.args, default_limit=1000, max_limit=5000)
    filter_query = {
        key: value for key, value in (
            ("user_id", request.args.get("user_id")),
            ("case_id", request.args.get("case_id")),
            ("result", request.args.get("result")),
        ) if value
    }
    if action and action != "all":
        filter_query["action"] = action
    total = db.audit_log.count_documents(filter_query)
    entries = audit.query(
        db,
        user_id=request.args.get("user_id"),
        case_id=request.args.get("case_id"),
        result=request.args.get("result"),
        actions=[action] if action and action != "all" else None,
        limit=limit, offset=offset,
    )
    return jsonify({
        "entries": entries,
        "events": [{"key": k, "label": v} for k, v in sorted(audit.EVENTS.items())],
        "pagination": paging.envelope(entries, total, limit, offset),
        "counts": {
            "total": db.audit_log.count_documents({}),
            "denied": db.audit_log.count_documents({"result": "denied"}),
            "restricted": db.audit_log.count_documents({"action": "restricted_accessed"}),
            "failed_logins": db.audit_log.count_documents({"action": "login_failed"}),
        },
    })


@admin_bp.route("/api/admin/system-status", methods=["GET"])
@requires_permission("system:status")
def system_status():
    """Operational snapshot: users, workload, access approvals and integrations."""
    from config import BANKS, get_db
    from services.mock_banks import MOCK_BANK_ENDPOINTS

    db = get_db()
    settings = get_settings(db)

    users_by_role = {
        role: db.users.count_documents({"role": role}) for role in ROLE_META
    }
    cases_by_status = {
        status: db.cases.count_documents({"status": status})
        for status in sorted({c.get("status") for c in db.cases.find({}, {"status": 1})} - {None})
    }

    return jsonify({
        "organization": ORGANIZATION,
        "users": {
            "total": db.users.count_documents({}),
            "active": db.users.count_documents({"status": "active"}),
            "suspended": db.users.count_documents({"status": "suspended"}),
            "by_role": users_by_role,
            "active_sessions": db.sessions.count_documents({}),
        },
        "workload": {
            "cases_by_status": cases_by_status,
            "open_cases": db.cases.count_documents({"status": {"$nin": ["closed", "normal"]}}),
            "reports_draft": db.analyst_reports.count_documents({"status": "draft"}),
            "reports_awaiting_review": db.analyst_reports.count_documents(
                {"status": {"$in": ["submitted", "clarification_requested"]}}),
            "evidence_items": db.case_evidence.count_documents({}),
            "updates_unacknowledged": db.investigation_updates.count_documents(
                {"acknowledged_at": None}),
        },
        "access_control": {
            "pending_requests": db.access_requests.count_documents({"status": "pending"}),
            "awaiting_bank": db.access_requests.count_documents({"status": "awaiting_bank"}),
            "partially_approved": db.access_requests.count_documents(
                {"status": "partially_approved"}),
            "rejected": db.access_requests.count_documents({"status": "rejected"}),
            "expired": db.access_requests.count_documents({"status": "expired"}),
            "active_authorizations": db.access_authorizations.count_documents(
                {"revoked_at": None, "expires_at": {"$gt": access_service._iso(access_service._now())}}),
            "restricted_records": db.restricted_subject_information.count_documents({}),
        },
        "configuration": {
            "anomaly_threshold": settings.get("anomaly_threshold"),
            "investigation_threshold": settings.get("investigation_threshold"),
            "mask_analyst_pii": settings.get("mask_analyst_pii"),
            "session_timeout_minutes": settings.get("session_timeout_minutes"),
            "demo_mode": settings.get("demo_mode"),
            "settings_updated_by": settings.get("updated_by"),
        },
        "bank_gateway": {
            "response_seconds": settings.get("bank_response_seconds"),
            "response_deadline_hours": settings.get("bank_response_deadline_hours"),
            "failure_rate": settings.get("bank_failure_rate"),
            "awaiting": db.access_requests.count_documents({"status": "awaiting_bank"}),
            "note": "A request for bank-held records is held until the bank answers, and "
                    "lapses if it does not answer within the response deadline.",
        },
        "integrations": {
            "banks": [{"id": b["id"], "name": b["name"], "mode": "simulated"}
                      for b in BANKS.values()],
            "bank_endpoints": len(MOCK_BANK_ENDPOINTS) if isinstance(MOCK_BANK_ENDPOINTS, dict)
            else len(list(MOCK_BANK_ENDPOINTS or [])),
            "live_payment_integration": False,
            "note": "All bank connectivity in this build is simulated on localhost. No live "
                    "payment, account-aggregator or government integration exists.",
        },
        "audit": {
            "total_events": db.audit_log.count_documents({}),
            "denied": db.audit_log.count_documents({"result": "denied"}),
            "recent_security_events": audit.security_events(db, limit=8),
        },
    })


@admin_bp.route("/api/settings", methods=["GET"])
@login_required
def read_settings():
    from config import get_db

    settings = get_settings(get_db())
    settings.pop("_id", None)
    settings["can_edit"] = current_user().get("role") == "admin"
    return jsonify(settings)


@admin_bp.route("/api/settings", methods=["PUT"])
@requires_permission("settings:manage")
def write_settings():
    from config import get_db

    db = get_db()
    actor = current_user()
    settings, error = update_settings(db, request.json or {}, updated_by=actor["username"])
    if error:
        return jsonify({"error": error}), 400

    audit.record(db, actor, "action", target="org_settings",
                 detail="Updated organisation risk and privacy settings",
                 metadata={k: v for k, v in settings.items() if k not in ("_id",)})
    settings.pop("_id", None)
    settings["can_edit"] = True
    return jsonify(settings)


@admin_bp.route("/api/admin/audit-integrity", methods=["GET"])
@requires_permission("audit:view_all")
def audit_integrity():
    """Recompute the audit chain and say whether the trail still reproduces.

    The trail being append-only over the API is a convention; this is the check that
    makes an edit made directly in the database visible. A break names the entry where
    the content and the recorded hash stopped agreeing.
    """
    from config import get_db

    db = get_db()
    raw_limit = request.args.get("limit")
    try:
        raw_limit = int(raw_limit) if raw_limit else None
    except (TypeError, ValueError):
        raw_limit = None
    result = audit.verify(db, limit=raw_limit)
    actor = current_user()
    audit.record(db, actor, "action", target="audit_chain",
                 detail=(f"Verified the audit chain: {result['entries']} entry(ies), "
                         + ("no break" if result["ok"]
                            else f"break at seq {result['break_seq']}: {result['reason']}")),
                 metadata={"ok": result["ok"], "entries": result["entries"],
                           "break_seq": result.get("break_seq")})
    return jsonify(result)


@admin_bp.route("/api/admin/threshold-backtest", methods=["GET"])
@requires_permission("settings:manage")
def threshold_backtest():
    """What the gate would do at each candidate threshold, against the demo scenarios.

    Thresholds are the one setting that silently changes which cases a person ever sees,
    so a change is offered with the evidence that produced it rather than by feel.
    """
    from config import get_db

    db = get_db()
    anomalies = backtest.parse_grid(request.args.get("anomaly"), backtest.DEFAULT_ANOMALY_GRID)
    investigations = backtest.parse_grid(request.args.get("investigation"),
                                         backtest.DEFAULT_INVESTIGATION_GRID)
    return jsonify(backtest.report(db, anomalies, investigations))


@admin_bp.route("/api/admin/threshold-backtest/apply", methods=["POST"])
@requires_permission("settings:manage")
def apply_thresholds():
    """Apply a threshold pair, recording the backtest that justified it.

    The audit entry carries the evidence, not just the numbers: a later reviewer can see
    which scenarios were considered and how they would have routed.
    """
    from config import get_db

    db = get_db()
    actor = current_user()
    payload = request.json or {}

    settings, error = update_settings(db, {
        "anomaly_threshold": payload.get("anomaly_threshold"),
        "investigation_threshold": payload.get("investigation_threshold"),
    }, updated_by=actor["username"])
    if error:
        return jsonify({"error": error}), 400

    evidence = backtest.report(db, current=settings)
    audit.record(db, actor, "action", target="org_settings",
                 detail=(f"Applied thresholds {settings['anomaly_threshold']:.2f} / "
                         f"{settings['investigation_threshold']:.2f} after a backtest: "
                         f"{(evidence.get('current', {}).get('result') or {}).get('agreed', '?')}"
                         f"/{len(evidence['observations'])} subjects route as designed"),
                 metadata={
                     "anomaly_threshold": settings["anomaly_threshold"],
                     "investigation_threshold": settings["investigation_threshold"],
                     "backtest": {
                         "agreed": (evidence.get("current", {}).get("result") or {}).get("agreed"),
                         "subjects": len(evidence["observations"]),
                         "misrouted": (evidence.get("current", {}).get("result") or {}).get("misrouted"),
                         "scores": {row["subject"]: row["score"]
                                    for row in evidence["observations"]},
                     },
                 })
    settings.pop("_id", None)
    return jsonify({"settings": settings,
                    "backtest": evidence.get("current", {}).get("result"),
                    "observations": evidence["observations"]})
