"""
Context Guard — Role Work Queues

The dashboard equivalent of "what is on my desk right now". Each role gets its own
counters and its own primary actions, computed from the same collections the rest of
the application writes to — nothing here is a static number.

Analyst counters are restricted to that analyst's assigned cases, so the figures and
the caseload beneath them cannot disagree.
"""

from datetime import datetime

AWAITING_DECISION = ("investigation", "context_verification", "escalated")
REPORT_REVIEW_STATES = ("submitted", "clarification_requested")
# A case is "active" while a human still has something to do on it.
ACTIVE_CASE_STATES = ("investigation", "context_verification", "escalated",
                      "awaiting_bank_response", "evidence_received", "analysis_complete",
                      "analyst_report_submitted", "compliance_review",
                      "additional_information_requested", "investigator_review")


def _iso_now():
    return datetime.utcnow().isoformat()


def _case_filter(case_ids):
    return {} if case_ids is None else {"case_id": {"$in": list(case_ids)}}


def analyst_queue(db, user, case_ids, cases):
    """Analyst: caseload, reporting progress and the feed of what changed."""
    ids = list(case_ids or [])
    my_reports = {
        "drafted": db.analyst_reports.count_documents(
            {"analyst_id": user["id"], "status": "draft"}),
        "submitted": db.analyst_reports.count_documents(
            {"analyst_id": user["id"], "status": {"$in": list(REPORT_REVIEW_STATES)}}),
        "clarification_requested": db.analyst_reports.count_documents(
            {"analyst_id": user["id"], "status": "clarification_requested"}),
        "reviewed": db.analyst_reports.count_documents(
            {"analyst_id": user["id"], "status": "reviewed"}),
    }

    high_priority = sorted(
        [c for c in cases if c.get("status") in AWAITING_DECISION],
        key=lambda c: -(c.get("score") or 0),
    )[:5]

    return {
        "role": "analyst",
        "headline": "My caseload",
        "metrics": [
            {"key": "active_cases", "label": "Active cases",
             "value": sum(1 for c in cases if c.get("status") in ACTIVE_CASE_STATES)},
            {"key": "new_cases", "label": "New / unstarted",
             "value": sum(1 for c in cases
                           if not c.get("pipeline_trace"))},
            {"key": "awaiting_investigation", "label": "Awaiting investigation",
             "value": sum(1 for c in cases if c.get("status") in AWAITING_DECISION)},
            {"key": "reports_drafted", "label": "Reports drafted",
             "value": my_reports["drafted"]},
            {"key": "reports_submitted", "label": "Reports submitted",
             "value": my_reports["submitted"]},
            {"key": "open_notes", "label": "Open questions / next steps",
             "value": db.case_notes.count_documents({
                 "case_id": {"$in": ids}, "resolved_at": None,
                 "kind": {"$in": ["question", "next_step"]}})},
            {"key": "marked_transactions", "label": "Transactions marked relevant",
             "value": db.case_transaction_relevance.count_documents(
                 {"case_id": {"$in": ids}, "relevant": True})},
            {"key": "recent_updates", "label": "Updates in the last 7 days",
             "value": db.investigation_updates.count_documents(
                 {**_case_filter(ids), "created_at": {"$gte": _seven_days_ago()}})},
        ],
        "high_priority": [
            {"id": c["id"], "title": c.get("title"), "score": c.get("score"),
             "status": c.get("status"), "assigned_to_name": c.get("assigned_to_name")}
            for c in high_priority
        ],
        "actions": [
            {"key": "open_case", "label": "Open case", "kind": "case"},
            {"key": "analyze", "label": "Analyse", "kind": "case"},
            {"key": "create_report", "label": "Create report", "tab": "report"},
        ],
        "report_progress": my_reports,
    }


def compliance_queue(db, user, case_ids, cases):
    """Compliance: what is waiting for review, and what needs authorising."""
    ids = None if case_ids is None else list(case_ids)
    scope = {} if ids is None else {"case_id": {"$in": ids}}

    pending_access = db.access_requests.count_documents({"status": "pending"})
    active_authorizations = db.access_authorizations.count_documents({
        "revoked_at": None, "expires_at": {"$gt": _iso_now()}})
    expiring = db.access_authorizations.count_documents({
        "revoked_at": None,
        "expires_at": {"$gt": _iso_now(), "$lt": _seven_days_ahead()}})

    return {
        "role": "compliance",
        "headline": "Review queue",
        "metrics": [
            {"key": "under_review", "label": "Cases under review",
             "value": sum(1 for c in cases
                          if c.get("status") in ("compliance_review", "evidence_received",
                                                 "analysis_complete"))},
            {"key": "new_reports", "label": "New analyst reports",
             "value": db.analyst_reports.count_documents(
                 {"status": "submitted", **(scope or {})})},
            {"key": "pending_clarifications", "label": "Awaiting clarification",
             "value": db.analyst_reports.count_documents({"status": "clarification_requested"})},
            {"key": "evidence_updates", "label": "Evidence added (7 days)",
             "value": db.case_evidence.count_documents(
                 {"created_at": {"$gte": _seven_days_ago()}})},
            {"key": "active_investigations", "label": "Active investigations",
             "value": sum(1 for c in cases if c.get("status") in ACTIVE_CASE_STATES)},
            {"key": "pending_access", "label": "Access requests awaiting admin",
             "value": pending_access},
            {"key": "active_authorizations", "label": "Authorisations you can use",
             "value": active_authorizations},
            {"key": "expiring_authorizations", "label": "Expiring within 7 days",
             "value": expiring},
            {"key": "recently_escalated", "label": "Escalated cases",
             "value": sum(1 for c in cases if c.get("status") == "escalated")},
            {"key": "unacknowledged_updates", "label": "Updates to acknowledge",
             "value": db.investigation_updates.count_documents(
                 {"acknowledged_at": None, **(scope or {})})},
        ],
        "high_priority": [
            {"id": c["id"], "title": c.get("title"), "score": c.get("score"),
             "status": c.get("status"), "assigned_to_name": c.get("assigned_to_name")}
            for c in sorted([c for c in cases if c.get("status") in AWAITING_DECISION],
                            key=lambda c: -(c.get("score") or 0))[:5]
        ],
        "actions": [
            {"key": "review_report", "label": "Review report", "view": "reports"},
            {"key": "evidence_vault", "label": "Open evidence vault", "tab": "evidence"},
            {"key": "request_access", "label": "Request restricted access", "tab": "restricted"},
            {"key": "escalate", "label": "Escalate", "kind": "case"},
        ],
        "access_control": {
            "pending": pending_access,
            "active_authorizations": active_authorizations,
            "expiring_soon": expiring,
        },
    }


def admin_queue(db, user, case_ids, cases):
    """Admin: identity, security and configuration state of the deployment."""
    from config import BANKS, ORGANIZATION
    from services.settings import get_settings
    from services.users import ROLE_META

    settings = get_settings(db)
    users_by_role = {role: db.users.count_documents({"role": role}) for role in ROLE_META}
    suspended = db.users.count_documents({"status": "suspended"})

    return {
        "role": "admin",
        "headline": "System overview",
        "metrics": [
            {"key": "active_users", "label": "Active users",
             "value": db.users.count_documents({"status": "active"})},
            {"key": "suspended_users", "label": "Suspended accounts", "value": suspended},
            {"key": "active_sessions", "label": "Live sessions",
             "value": db.sessions.count_documents({})},
            {"key": "pending_access", "label": "Access requests awaiting you",
             "value": db.access_requests.count_documents({"status": "pending"})},
            {"key": "audit_events", "label": "Audit events recorded",
             "value": db.audit_log.count_documents({})},
            {"key": "denied_events", "label": "Access refusals",
             "value": db.audit_log.count_documents({"result": "denied"})},
            {"key": "failed_logins", "label": "Failed sign-ins",
             "value": db.audit_log.count_documents({"action": "login_failed"})},
            {"key": "restricted_accessed", "label": "Restricted records released",
             "value": db.audit_log.count_documents({"action": "restricted_accessed"})},
        ],
        "users_by_role": [
            {"role": role, "label": meta["label"], "count": users_by_role.get(role, 0)}
            for role, meta in ROLE_META.items()
        ],
        "integration_status": [
            {"name": bank["name"], "mode": "simulated", "status": "available"}
            for bank in BANKS.values()
        ],
        "configuration": {
            "anomaly_threshold": settings.get("anomaly_threshold"),
            "investigation_threshold": settings.get("investigation_threshold"),
            "mask_analyst_pii": settings.get("mask_analyst_pii"),
            "session_timeout_minutes": settings.get("session_timeout_minutes"),
            "updated_by": settings.get("updated_by"),
            "organization": ORGANIZATION["name"],
            "environment": ORGANIZATION["environment"],
        },
        "health": {
            "database": "connected",
            "api": "responding",
            "cases": db.cases.count_documents({}),
            "transactions": db.transactions.count_documents({}),
            "reports": db.analyst_reports.count_documents({}),
            "evidence": db.case_evidence.count_documents({}),
            "notes": db.case_notes.count_documents({}),
        },
        "actions": [
            {"key": "manage_users", "label": "Manage users", "view": "users"},
            {"key": "manage_roles", "label": "Manage roles", "view": "users"},
            {"key": "access_requests", "label": "Access requests", "view": "access"},
            {"key": "audit_logs", "label": "Audit logs", "view": "audit"},
            {"key": "system_settings", "label": "System settings", "view": "settings"},
        ],
    }


def build(db, user, case_ids, cases):
    """Select the queue for the caller's role."""
    role = user.get("role")
    if role == "analyst":
        return analyst_queue(db, user, case_ids, cases)
    if role == "compliance":
        return compliance_queue(db, user, case_ids, cases)
    if role == "admin":
        return admin_queue(db, user, case_ids, cases)
    return {"role": role, "headline": "Dashboard", "metrics": [], "actions": []}


def _seven_days_ago():
    from datetime import timedelta
    return (datetime.utcnow() - timedelta(days=7)).isoformat()


def _seven_days_ahead():
    from datetime import timedelta
    return (datetime.utcnow() + timedelta(days=7)).isoformat()
