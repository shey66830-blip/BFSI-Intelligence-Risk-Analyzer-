"""
Context Guard — Route Guards

Decorators that turn an authenticated session into an authorised request:

    @login_required                      -> 401 unless a valid session token is sent
    @requires_permission("users:manage") -> 401/403 unless the role holds the permission

Handlers read the caller from `g.user` / `g.permissions`, never from request data,
which is what stops a client from simply claiming a role.
"""

from functools import wraps

from flask import g, jsonify, request

from config import get_db
from services import access
from services.users import has_permission, permissions_for, resolve_session


def extract_token():
    """Read the session token from the Authorization header."""
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.headers.get("X-Session-Token") or None


def _authenticate():
    """Populate g.user / g.grants / g.permissions. True when a session is valid.

    Authority has two sources: the role in the permission matrix, and any
    authorisation that has released a capability to this identity. The second is
    deliberately resolved per request — a grant that expires stops working the
    moment it lapses, with no restart and no stale session holding it open.
    """
    db = get_db()
    token = extract_token()
    user = resolve_session(db, token)

    grants = access.active_unlocks(db, user["id"]) if user else set()
    g.db = db
    g.token = token
    g.user = user
    g.grants = grants
    g.permissions = (set(permissions_for(user["role"])) | grants) if user else set()
    return user is not None


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not _authenticate():
            return jsonify({
                "error": "Authentication required. Sign in to continue.",
                "code": "unauthenticated",
            }), 401
        return fn(*args, **kwargs)
    return wrapper


def requires_permission(permission):
    """Require a specific permission in addition to a valid session."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not _authenticate():
                return jsonify({
                    "error": "Authentication required. Sign in to continue.",
                    "code": "unauthenticated",
                }), 401
            if not can(permission):
                return jsonify({
                    "error": f"Your role ({g.user.get('role')}) is not permitted to do this.",
                    "code": "forbidden",
                    "required_permission": permission,
                }), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ── Helpers for handlers ─────────────────────────────────────────────────────

def current_user():
    return getattr(g, "user", None)


def can(permission):
    """Role permission, or a capability a live authorisation has released."""
    user = current_user()
    if not user:
        return False
    if permission in getattr(g, "grants", set()):
        return True
    return has_permission(user.get("role"), permission)


def case_access(case, user=None):
    """Can this identity see this case at all? Returns (allowed, reason)."""
    user = user or current_user()
    if not user:
        return False, "Not signed in"
    if has_permission(user["role"], "cases:view_all"):
        return True, None
    if case.get("assigned_to") == user["id"]:
        return True, None
    return False, "This case is not assigned to you"


def load_case(case_id, permission=None, require_access=True):
    """Fetch a case for the current caller, enforcing scope and permission.

    Returns `(case, error)` where error is a ready-to-return `(payload, status)` tuple
    or None. Callers must be inside @login_required so `g.user` is populated.
    """
    db = get_db()
    user = current_user()
    case = db.cases.find_one({"id": case_id})
    if not case:
        return None, ({"error": "Case not found", "code": "not_found"}, 404)

    if require_access:
        allowed, reason = case_access(case, user)
        if not allowed:
            from services import audit
            audit.record(db, user, "access_denied", target=case_id, detail=reason,
                         case_id=case_id, resource_type="investigation_case",
                         result="denied", reason=reason)
            return None, ({"error": reason, "code": "forbidden"}, 403)

    if permission and not can(permission):
        from services import audit
        audit.record(db, user, "access_denied", target=case_id,
                     detail=f"Missing permission {permission}", case_id=case_id,
                     resource_type="investigation_case", result="denied",
                     reason=f"requires {permission}")
        return None, ({
            "error": f"Your role ({user.get('role')}) is not permitted to do this.",
            "code": "forbidden",
            "required_permission": permission,
        }, 403)

    return case, None


def visible_case_ids(db, user=None):
    """Case ids the identity may see. None means 'everything'."""
    user = user or current_user()
    if not user:
        return []
    if has_permission(user["role"], "cases:view_all"):
        return None
    return [c["id"] for c in db.cases.find({"assigned_to": user["id"]}, {"id": 1})]
