"""
Context Guard — L3 · Boot Posture Guard

Closes G-02 and the boot half of G-04.

Two of the worst findings in this codebase were not vulnerabilities in a handler,
they were *defaults that were wrong for production and right for a demo*:

    FLASK_DEBUG     defaulted to "true"       → the Werkzeug debugger, which is
                                               remote code execution by design,
                                               listening on 0.0.0.0
    demo_mode       defaulted to True         → /api/auth/demo-accounts serves
                                               working credentials over the wire
    ALLOWED_ORIGINS unset                     → an open API

A default cannot be "safe in development and safe in production" at the same time.
So the resolution is not a better default, it is a **refusal**: the application
will not start in a production environment in a configuration that is only
acceptable for a demonstration. It fails loudly at boot rather than quietly in
production, which is the only place these mistakes can be caught cheaply.

This is intentionally not overridable. No environment variable relaxes it; the
escape hatch is to fix the configuration.
"""

import os

from . import policy


class InsecurePosture(RuntimeError):
    """Raised when production startup is attempted in a demo-grade configuration."""


def _problems(db=None):
    """Everything wrong with the current posture. Empty means safe to start."""
    found = []

    debug = (os.environ.get("FLASK_DEBUG", "true") or "true").lower() == "true"
    if policy.IS_PRODUCTION and debug:
        found.append(
            "FLASK_DEBUG is on in a production environment. The Werkzeug debugger "
            "allows arbitrary code execution; set FLASK_DEBUG=false."
        )

    if policy.IS_PRODUCTION and not os.environ.get("ALLOWED_ORIGINS", "").strip():
        found.append(
            "ALLOWED_ORIGINS is not set in a production environment. The API would "
            "fall back to the development allowlist; name the console origins."
        )

    mongo_uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
    if policy.IS_PRODUCTION and ("localhost" in mongo_uri or "127.0.0.1" in mongo_uri):
        found.append(
            "MONGO_URI points at a local, unauthenticated database in a production "
            "environment. Configure an authenticated, network-isolated cluster."
        )

    if db is not None and policy.IS_PRODUCTION:
        settings = db.settings.find_one({"id": "org_settings"}) or {}
        if settings.get("demo_mode", True):
            found.append(
                "demo_mode is enabled in a production environment, so synthetic "
                "credentials are served by /api/auth/demo-accounts."
            )
        synthetic = db.users.count_documents({"is_synthetic": True})
        if synthetic:
            found.append(
                f"The database holds {synthetic} synthetic demonstration account(s) "
                "in a production environment."
            )

    return found


def assert_posture(db=None):
    """Refuse to run a production configuration that is only fit for a demo."""
    found = _problems(db)
    if found:
        raise InsecurePosture(
            "Refusing to start in a production environment:\n  - "
            + "\n  - ".join(found)
        )
    return True
