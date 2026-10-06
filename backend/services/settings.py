"""
Context Guard — Organisation Settings

Admin-editable settings that actually drive backend behaviour: the two risk
thresholds used by the anomaly gate, the masking policy applied to analysts,
session lifetime and whether a decision rationale is mandatory.
"""

from datetime import datetime

from config import (
    ANOMALY_THRESHOLD,
    BANK_FAILURE_RATE,
    BANK_RESPONSE_DEADLINE_HOURS,
    BANK_RESPONSE_SECONDS,
    GRAPH_MAX_HOPS,
    INVESTIGATION_THRESHOLD,
)
from services.users import DEFAULT_SESSION_MINUTES

SETTINGS_ID = "org_settings"

DEFAULTS = {
    "id": SETTINGS_ID,
    "anomaly_threshold": ANOMALY_THRESHOLD,
    "investigation_threshold": INVESTIGATION_THRESHOLD,
    "mask_analyst_pii": True,
    "require_decision_rationale": True,
    "session_timeout_minutes": DEFAULT_SESSION_MINUTES,
    "hospital_context_mitigation": True,
    # Bank gateway. A bank is not a local function call: the platform sends a request
    # and the answer comes back later, or not at all. These drive that channel.
    "bank_response_seconds": BANK_RESPONSE_SECONDS,
    "bank_response_deadline_hours": BANK_RESPONSE_DEADLINE_HOURS,
    "bank_failure_rate": BANK_FAILURE_RATE,
    # How far the network walk reaches from a case's subject. Wider finds more of the
    # pattern and widens scope, so it is bounded and admin-settable.
    "graph_max_hops": GRAPH_MAX_HOPS,
    "demo_mode": True,
}

# Which keys an admin is allowed to change and how they are validated.
EDITABLE = {
    "anomaly_threshold": (float, 0.0, 0.99),
    "investigation_threshold": (float, 0.01, 1.0),
    "session_timeout_minutes": (int, 5, 10080),
    "bank_response_seconds": (int, 0, 86400),
    "bank_response_deadline_hours": (int, 1, 336),
    "bank_failure_rate": (float, 0.0, 1.0),
    "graph_max_hops": (int, 1, 5),
}

TOGGLES = ("mask_analyst_pii", "require_decision_rationale", "hospital_context_mitigation")


def get_settings(db):
    """Current org settings, back-filled with defaults for anything missing."""
    doc = db.settings.find_one({"id": SETTINGS_ID}) or {}
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in doc.items() if k not in ("_id", "id")})
    return merged


def update_settings(db, payload, updated_by=None):
    """Validate and persist settings. Returns (settings, error)."""
    current = get_settings(db)
    updates = {}

    for key, (cast, low, high) in EDITABLE.items():
        if key not in payload or payload[key] is None or payload[key] == "":
            continue
        try:
            value = cast(payload[key])
        except (TypeError, ValueError):
            return None, f"{key} must be a number"
        if not (low <= value <= high):
            return None, f"{key} must be between {low} and {high}"
        updates[key] = value

    for key in TOGGLES:
        if key in payload and payload[key] is not None:
            updates[key] = bool(payload[key])

    # Anomaly gate must stay below the investigation gate, or the routing breaks.
    anomaly = updates.get("anomaly_threshold", current["anomaly_threshold"])
    investigation = updates.get("investigation_threshold", current["investigation_threshold"])
    if anomaly >= investigation:
        return None, "Anomaly threshold must be lower than the investigation threshold"

    if not updates:
        return current, None

    updates["updated_at"] = datetime.utcnow().isoformat()
    updates["updated_by"] = updated_by
    db.settings.update_one({"id": SETTINGS_ID}, {"$set": updates}, upsert=True)
    return get_settings(db), None
