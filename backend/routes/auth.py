"""
Context Guard — Authentication Routes

    POST /api/auth/login           username + password -> session token
    POST /api/auth/logout          revoke the current session
    GET  /api/auth/me              the signed-in identity + its permissions
    GET  /api/auth/demo-accounts   synthetic accounts (demo mode only)
"""

from flask import Blueprint, g, jsonify, request

from config import get_db
from middleware import current_user, login_required
from services import audit
from services.settings import get_settings
from services.users import (
    DEMO_USERS, ROLE_META, authenticate, public_user, revoke_session,
)

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/api/auth/login", methods=["POST"])
def login():
    db = get_db()
    data = request.json or {}
    settings = get_settings(db)

    user, token, error = authenticate(
        db,
        data.get("username"),
        data.get("password"),
        timeout_minutes=int(settings.get("session_timeout_minutes", 480)),
    )
    if error:
        audit.record(
            db, None, "login_failed", target=(data.get("username") or "").strip().lower(),
            detail="Rejected sign-in attempt", system=True,
        )
        return jsonify({"error": error}), 401

    audit.record(db, user, "login", target=user["username"],
                 detail=f"Signed in as {ROLE_META.get(user['role'], {}).get('label', user['role'])}")

    return jsonify({"token": token, "user": public_user(user)})


@auth_bp.route("/api/auth/logout", methods=["POST"])
@login_required
def logout():
    db = get_db()
    user = current_user()
    revoke_session(db, g.token)
    audit.record(db, user, "logout", target=user["username"], detail="Session ended")
    return jsonify({"ok": True})


@auth_bp.route("/api/auth/me", methods=["GET"])
@login_required
def me():
    db = get_db()
    user = current_user()
    settings = get_settings(db)
    return jsonify({
        "user": public_user(user),
        "settings": {
            "mask_analyst_pii": settings.get("mask_analyst_pii", True),
            "session_timeout_minutes": settings.get("session_timeout_minutes"),
            "demo_mode": settings.get("demo_mode", True),
        },
    })


@auth_bp.route("/api/auth/demo-accounts", methods=["GET"])
def demo_accounts():
    """The synthetic accounts, so the demo login page can offer one-click sign-in.

    Only exposed while the org runs in demo mode — a production deployment returns
    an empty list and would replace this with a real identity provider.
    """
    db = get_db()
    settings = get_settings(db)
    if not settings.get("demo_mode", True):
        return jsonify([])

    return jsonify([
        {
            "username": spec["username"],
            "password": spec["password"],
            "name": spec["name"],
            "role": spec["role"],
            "role_label": ROLE_META.get(spec["role"], {}).get("label", spec["role"]),
            "description": ROLE_META.get(spec["role"], {}).get("description", ""),
            "title": spec["title"],
        }
        for spec in DEMO_USERS
    ])
