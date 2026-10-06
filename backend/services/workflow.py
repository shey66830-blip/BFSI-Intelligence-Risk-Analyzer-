"""
Context Guard — Case Status Workflow

The investigation lifecycle as a state machine. Cases are not forced through every
state: a case can move straight from monitoring to closed when context explains the
activity, and most cases never reach the later states.

Existing statuses keep working — anything not listed in `STAGES` is treated as a
custom state that only an administrator may set.
"""

# ── Lifecycle ────────────────────────────────────────────────────────────────
#
# order is for display and for "how far along is this case" comparisons only.

STAGES = [
    {"key": "new", "order": 1, "label": "New",
     "description": "Created, not yet triaged."},
    {"key": "monitoring", "order": 2, "label": "Monitoring",
     "description": "Activity is being watched without a formal request."},
    {"key": "context_verification", "order": 3, "label": "Context Verification",
     "description": "A bank has been asked to explain the activity."},
    {"key": "investigation", "order": 4, "label": "Investigation",
     "description": "Open investigation; evidence is being gathered."},
    {"key": "investigation_requested", "order": 5, "label": "Investigation Requested",
     "description": "A formal investigation request has been issued."},
    {"key": "awaiting_bank_response", "order": 6, "label": "Awaiting Bank Response",
     "description": "Requests are with the banks."},
    {"key": "evidence_received", "order": 7, "label": "Evidence Received",
     "description": "Bank responses have landed and are being filed."},
    {"key": "analysis_complete", "order": 8, "label": "Analysis Complete",
     "description": "Analysis is finished; a report is being prepared."},
    {"key": "analyst_report_submitted", "order": 9, "label": "Analyst Report Submitted",
     "description": "An analyst report is with compliance for review."},
    {"key": "compliance_review", "order": 10, "label": "Compliance Review",
     "description": "Compliance is reviewing the report and the evidence."},
    {"key": "additional_info_requested", "order": 11, "label": "Additional Information Requested",
     "description": "The case was returned to the analyst for clarification."},
    {"key": "investigator_review", "order": 12, "label": "Investigator Review",
     "description": "Awaiting the authorised investigator's final decision."},
    {"key": "escalated", "order": 13, "label": "Escalated",
     "description": "Referred onward with the report attached."},
    {"key": "closed", "order": 14, "label": "Closed",
     "description": "Concluded — with a recorded reason."},
    {"key": "normal", "order": 0, "label": "Normal",
     "description": "Legacy state: activity was never escalated."},
]

STAGE_BY_KEY = {stage["key"]: stage for stage in STAGES}

# Which moves each role may make. Administrators may also correct any state.
TRANSITIONS = {
    "new": ["monitoring", "context_verification", "investigation", "closed"],
    "normal": ["monitoring", "context_verification", "investigation", "closed"],
    "monitoring": ["context_verification", "investigation", "closed"],
    "context_verification": ["investigation", "investigation_requested", "closed"],
    "investigation": ["investigation_requested", "awaiting_bank_response", "evidence_received",
                      "analysis_complete", "closed"],
    "investigation_requested": ["awaiting_bank_response", "evidence_received", "closed"],
    "awaiting_bank_response": ["evidence_received", "closed"],
    "evidence_received": ["analysis_complete", "closed"],
    "analysis_complete": ["analyst_report_submitted", "closed"],
    "analyst_report_submitted": ["compliance_review", "additional_info_requested", "closed"],
    "compliance_review": ["additional_info_requested", "investigator_review", "escalated", "closed"],
    "additional_info_requested": ["analysis_complete", "analyst_report_submitted", "compliance_review", "closed"],
    "investigator_review": ["escalated", "closed"],
    "escalated": ["closed"],
    "closed": ["investigation"],   # reopened with new evidence
}

# Roles that may move a case *into* a given state.
ROLES_FOR_TARGET = {
    "monitoring": {"analyst", "compliance", "admin"},
    "context_verification": {"compliance", "admin"},
    "investigation": {"compliance", "admin"},
    "investigation_requested": {"compliance", "admin"},
    "awaiting_bank_response": {"compliance", "admin"},
    "evidence_received": {"analyst", "compliance", "admin"},
    "analysis_complete": {"analyst", "compliance", "admin"},
    "analyst_report_submitted": {"analyst", "admin"},
    "compliance_review": {"compliance", "admin"},
    "additional_info_requested": {"compliance", "admin"},
    "investigator_review": {"compliance", "admin"},
    "escalated": {"compliance", "admin"},
    "closed": {"analyst", "compliance", "admin"},
}

# States whose label/colour the UI needs even for unknown values.
TERMINAL = {"closed", "escalated"}


def label_for(status):
    stage = STAGE_BY_KEY.get(status)
    return stage["label"] if stage else (status or "Unknown").replace("_", " ").title()


def order_for(status):
    stage = STAGE_BY_KEY.get(status)
    return stage["order"] if stage else 99


def can_transition(current, target, role):
    """Return (allowed, reason). Explains refusals so the UI can show them.

    Cases are not forced through every state. A move is allowed when it is either
    explicitly listed, or a *forward* move to a later stage that this role is
    permitted to set. Backward moves are corrections and belong to an administrator,
    with one exception: a closed case can be reopened into investigation.
    """
    if target == current:
        return False, f"The case is already in {label_for(target)}"

    if target not in STAGE_BY_KEY:
        if role == "admin":
            return True, None
        return False, f"Unknown status: {target}"

    if current not in STAGE_BY_KEY:
        # A legacy/custom state: only an administrator may move it out.
        if role == "admin":
            return True, None
        return False, f"A case in '{label_for(current)}' can only be moved by an administrator"

    permitted_roles = ROLES_FOR_TARGET.get(target, set())
    if role not in permitted_roles and role != "admin":
        return False, (f"Your role cannot move a case to {label_for(target)}")

    if role == "admin":
        return True, None

    listed = TRANSITIONS.get(current) or []
    if target in listed:
        return True, None

    if order_for(target) > order_for(current):
        return True, None

    return False, (f"A case cannot move from {label_for(current)} to "
                   f"{label_for(target)} directly")


def next_states(current, role):
    """States this role may move the case into right now."""
    return [
        stage["key"] for stage in STAGES
        if can_transition(current, stage["key"], role)[0]
    ]


def progress(status):
    """0.0–1.0 position in the lifecycle, for a progress indicator."""
    order = order_for(status)
    if order >= 99:
        return 0.0
    return round(order / max(order_for(s["key"]) for s in STAGES), 2)
