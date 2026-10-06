"""
Context Guard — Configuration
Environment variables for MongoDB and application settings.
"""

import os
from pymongo import MongoClient
from pymongo.server_api import ServerApi

# ── MongoDB ──────────────────────────────────────────────────────────────────

MONGO_URI = os.environ.get(
    "MONGO_URI",
    "mongodb://localhost:27017"
)
MONGO_DB = os.environ.get("MONGO_DB", "context_guard")

_client = None
_db = None


def get_db():
    """Return a shared MongoDB database handle (lazy singleton)."""
    global _client, _db
    if _db is None:
        _client = MongoClient(MONGO_URI, server_api=ServerApi("1"))
        _db = _client[MONGO_DB]
        # Create indexes for fast lookups
        _db.transactions.create_index("case_id")
        _db.transactions.create_index("entity_id")
        _db.transactions.create_index("bank_id")
        _db.transactions.create_index("id")
        _db.transactions.create_index("timestamp")
        _db.cases.create_index("status")
        _db.cases.create_index("assigned_to")
        _db.entities.create_index("bank_id")
        _db.graph_edges.create_index([("source", 1), ("target", 1)])
        _db.graph_edges.create_index("edge_type")
        _db.bank_reports.create_index("case_id")

        # Identity & access control
        _db.users.create_index("username", unique=True)
        _db.users.create_index("role")
        _db.sessions.create_index("token_hash", unique=True)
        _db.sessions.create_index("expires_at")

        # Evidence, reports and authorisations
        _db.analyst_reports.create_index("case_id")
        _db.analyst_reports.create_index("analyst_id")
        _db.analyst_reports.create_index([("case_id", 1), ("version", -1)])
        _db.case_evidence.create_index("case_id")
        _db.case_evidence.create_index("access_level")
        _db.investigation_updates.create_index("case_id")
        _db.investigation_updates.create_index([("case_id", 1), ("created_at", -1)])
        _db.access_requests.create_index("case_id")
        _db.access_requests.create_index("status")
        _db.access_requests.create_index("requested_by")
        _db.access_authorizations.create_index("granted_to")
        _db.access_authorizations.create_index("expires_at")
        _db.restricted_subject_information.create_index("case_id")
        _db.notifications.create_index("user_id")
        _db.audit_log.create_index("user_id")
        _db.audit_log.create_index("timestamp")
        _db.audit_log.create_index("case_id")
        _db.audit_log.create_index([("result", 1), ("timestamp", -1)])
        # The tamper-evident chain is read in sequence order every time it is verified.
        _db.audit_log.create_index("seq")
        _db.audit_chain.create_index("seq")
        _db.cases.create_index("id")
        _db.case_notes.create_index("case_id")
        _db.case_notes.create_index([("case_id", 1), ("created_at", -1)])
        _db.case_notes.create_index("author_id")
        # One relevance annotation per (case, transaction): re-marking updates it.
        _db.case_transaction_relevance.create_index(
            [("case_id", 1), ("transaction_id", 1)], unique=True)
        _db.case_transaction_relevance.create_index("case_id")
        _db.case_evidence.create_index("evidence_id")
        _db.analyst_reports.create_index("status")
        _db.investigation_updates.create_index("acknowledged_at")
        try:
            # Email addresses identify a login, so they must stay unique.
            _db.users.create_index("email", unique=True, sparse=True)
        except Exception as exc:  # pragma: no cover - depends on existing data
            print(f"  Warning: could not create unique email index: {exc}")
    return _db


# ── Application ──────────────────────────────────────────────────────────────

FLASK_PORT = int(os.environ.get("FLASK_PORT", 5000))
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "true").lower() == "true"

# ── Organisation ─────────────────────────────────────────────────────────────
# The operating entity shown on the login page and in the application header.
ORGANIZATION = {
    "name": os.environ.get("ORGANIZATION_NAME", "Northbridge Financial Intelligence"),
    "short": os.environ.get("ORGANIZATION_SHORT", "Northbridge FI"),
    "environment": os.environ.get("APP_ENVIRONMENT", "Demonstration"),
}

# Maximum duration a restricted-information authorisation may be granted for.
MAX_ACCESS_DURATION_DAYS = int(os.environ.get("MAX_ACCESS_DURATION_DAYS", 30))

# ── Bank gateway ─────────────────────────────────────────────────────────────
# A request for bank-held records leaves the platform and is answered later, or not
# at all. These are the org-settings defaults: no artificial latency and no injected
# failures, so the demonstration flows cleanly. Raising the latency or the failure
# rate makes the channel behave like a real consent desk.
# How far the network expansion walks from a case's subject before it stops widening
# scope. Admin-overridable; capped by graph_engine.MAX_HOPS_CAP.
GRAPH_MAX_HOPS = int(os.environ.get("GRAPH_MAX_HOPS", 2))

BANK_RESPONSE_SECONDS = int(os.environ.get("BANK_RESPONSE_SECONDS", 0))
BANK_RESPONSE_DEADLINE_HOURS = int(os.environ.get("BANK_RESPONSE_DEADLINE_HOURS", 48))
BANK_FAILURE_RATE = float(os.environ.get("BANK_FAILURE_RATE", 0.0))

# Risk thresholds
ANOMALY_THRESHOLD = float(os.environ.get("ANOMALY_THRESHOLD", 0.35))
INVESTIGATION_THRESHOLD = float(os.environ.get("INVESTIGATION_THRESHOLD", 0.65))

# ── Banks ────────────────────────────────────────────────────────────────────

BANKS = {
    "bank_a": {
        "id": "bank_a",
        "name": "HDFC Bank",
        "country": "IN",
        "color": "#004c8f",
    },
    "bank_b": {
        "id": "bank_b",
        "name": "ICICI Bank",
        "country": "IN",
        "color": "#f58220",
    },
    "bank_c": {
        "id": "bank_c",
        "name": "Axis Bank",
        "country": "IN",
        "color": "#97144d",
    },
}
