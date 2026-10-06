"""
Context Guard — Flask Application

Main entry point that wires together all blueprints and initializes MongoDB.
"""

import os
from datetime import date, datetime

from bson import ObjectId
from flask import Flask
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from config import get_db, FLASK_PORT, FLASK_DEBUG
from security import assert_posture, install as install_security
from services.seed import seed_database
from services.seed_access import ensure_evidence_baselines, ensure_restricted_information
from services.users import ensure_case_assignments, ensure_users
from routes.cases import cases_bp
from routes.pipeline import pipeline_bp
from routes.graph import graph_bp
from routes.ingest import ingest_bp
from routes.auth import auth_bp
from routes.admin import admin_bp
from routes.audit import audit_bp
from routes.reports import reports_bp
from routes.evidence import evidence_bp
from routes.access import access_bp
from routes.notifications import notifications_bp
from routes.investigation import investigation_bp


def _json_default(value):
    """Make Mongo documents serialisable without touching every route.

    Handlers return records as they were read, so `_id` and timestamps reach
    `jsonify` constantly. Doing it here means a new endpoint cannot leak an
    ObjectId into a response by forgetting to strip it.
    """
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def create_app():
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.json.default = _json_default
    app.json.sort_keys = False
    # Application-layer security controls, wired in one place so that "what
    # protects this app?" is answerable by reading one line: L2 origin allowlist,
    # L3 throttling and input validation, L1 response headers, L6 log scrubbing.
    # Previously this line was `CORS(..., origins="*")` — an open API (G-01).
    install_security(app)

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(pipeline_bp)
    app.register_blueprint(graph_bp)
    app.register_blueprint(ingest_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(evidence_bp)
    app.register_blueprint(access_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(investigation_bp)

    return app


def init_database():
    """Initialize MongoDB with seed data, identity records and case ownership."""
    db = get_db()

    if db.entities.count_documents({}) == 0:
        print("Initializing database with seed data...")
        stats = seed_database(db)
        print(f"  Database initialized: {stats}")
    else:
        print(f"Database already populated: {db.entities.count_documents({})} entities")

    # Identity + ownership are idempotent: safe on every boot.
    created = ensure_users(db)
    if created:
        print(f"  Synthetic accounts created: {', '.join(created)}")
        from services import audit
        audit.record(db, None, "system", target="identity",
                     detail=f"Provisioned {len(created)} synthetic accounts", system=True)
    else:
        print(f"  Accounts already present: {db.users.count_documents({})} users")
    db.sessions.create_index("token_hash", unique=True)

    assigned = ensure_case_assignments(db)
    if assigned:
        print(f"  Case ownership set for: {', '.join(sorted(set(assigned)))}")

    restricted = ensure_restricted_information(db)
    if restricted:
        print(f"  Synthetic restricted subject records created: {restricted}")
    baselined = ensure_evidence_baselines(db)
    if baselined:
        print(f"  Evidence filed into case vaults: {baselined} item(s)")

    print(f"  Cases: {db.cases.count_documents({})} | Audit entries: {db.audit_log.count_documents({})}")
    print(f"  Reports: {db.analyst_reports.count_documents({})} | Evidence: {db.case_evidence.count_documents({})} "
          f"| Access requests: {db.access_requests.count_documents({})}")
    print(f"  Notes: {db.case_notes.count_documents({})} | Marked transactions: "
          f"{db.case_transaction_relevance.count_documents({'relevant': True})}")


# Create app
app = create_app()


if __name__ == "__main__":
    print(f"Starting Context Guard on port {FLASK_PORT}...")
    init_database()
    # Refuse to serve a demonstration-grade configuration in a production
    # environment: debug on, an unauthenticated database, or synthetic
    # credentials present (G-02, G-04).
    assert_posture(get_db())
    app.run(debug=FLASK_DEBUG, port=FLASK_PORT, host="0.0.0.0")
