"""
Context Guard — Users, Sessions & Permissions

Synthetic accounts for the demo: analyst, compliance officer, organisation admin.
Designed so the storage layer can be swapped for a real identity provider later —
routes only depend on `authenticate()`, `current_user()` and the permission matrix.

Auth flow:
    password --verify--> user --issue--> opaque session token (stored hashed)
    token --Authorization: Bearer--> session lookup --> user
"""

import hashlib
import secrets
from datetime import datetime, timedelta

from werkzeug.security import check_password_hash, generate_password_hash

# ── Permission matrix ────────────────────────────────────────────────────────
#
# One place decides what a role may do. Routes ask for a permission name, never
# for a role name, so adding a role (e.g. "fiu_liaison") is a data change only.

ANALYST_PERMISSIONS = {
    "cases:view_assigned",     # only cases assigned to them
    "cases:investigate",       # run the pipeline on an assigned case
    "cases:decide_limited",    # close / request context — cannot escalate
    "cases:status_change",     # move a case along the allowed analyst transitions
    "txn:view",                # transactions, with PII masked
    "graph:view",              # graph limited to entities on their cases
    "reports:create",          # draft an analyst investigation report
    "reports:submit",          # submit a draft to compliance
    "evidence:add",            # file evidence into a case vault
    "updates:post",            # post an investigation update
    "access:request",          # ask for locked information and capabilities
    "audit:view_own",
}

COMPLIANCE_PERMISSIONS = {
    "cases:view_all",
    "cases:investigate",
    "cases:decide",            # full decision set, including escalate to FIU
    "cases:assign",
    "cases:status_change",
    "reports:view",
    "reports:review",          # review and act on submitted analyst reports
    "reports:clarify",         # send a report back for clarification
    "evidence:manage",         # organise the vault: status, folder, access level
    "evidence:add",
    "updates:acknowledge",
    "updates:post",
    "access:request",          # request restricted subject information
    "txn:view",
    "txn:view_unmasked",       # sees real identifiers
    "graph:view",
    "graph:view_all",
    "audit:view_all",
}

ADMIN_PERMISSIONS = (
    COMPLIANCE_PERMISSIONS
    | ANALYST_PERMISSIONS
    | {
        "users:manage",
        "settings:manage",
        "audit:view_all",
        "access:approve",      # approve / reject / clarify access requests
        "system:status",
        "system:configure",
    }
) - {
    # Separation of duties: whoever approves restricted-information requests must not
    # be able to raise one. The approver is a compliance officer, and the service
    # refuses self-approval as a second line of defence.
    "access:request",
}

# Permissions that are deliberately NOT part of any role, because they are granted
# by an authorisation record rather than by role alone.
AUTHORISATION_GATED = {
    "restricted:view",         # only with an active, in-scope access authorisation
    "txn:view_unmasked",       # releasable by a justified, expiring authorisation
    "graph:view_all",
    "evidence:manage",
}

ROLE_PERMISSIONS = {
    "analyst": ANALYST_PERMISSIONS,
    "compliance": COMPLIANCE_PERMISSIONS,
    "admin": ADMIN_PERMISSIONS,
}

ROLE_META = {
    "analyst": {
        "label": "Analyst",
        "code": "ANALYST",
        "description": "Investigates assigned cases and produces the investigation report.",
        "dashboard": "my_cases",
        "responsibility": "Analysis and reporting",
    },
    "compliance": {
        "label": "Compliance Officer",
        "code": "COMPLIANCE_OFFICER",
        "description": "Reviews analyst reports, curates the evidence vault and manages access to restricted information.",
        "dashboard": "review_queue",
        "responsibility": "Review and evidence governance",
    },
    "admin": {
        "label": "Organisation Administrator",
        "code": "ORGANIZATION_ADMIN",
        "description": "Manages users, roles, organisation policy, restricted-information approvals and the audit trail.",
        "dashboard": "system_overview",
        "responsibility": "Identity, policy and authorisation",
    },
}

# Decisions the limited (analyst) permission set may record.
LIMITED_DECISIONS = {"close_explained", "request_more_context", "continue_investigation"}

DEFAULT_SESSION_MINUTES = 480
MAX_FAILED_ATTEMPTS = 5

# Every login is an email address as well as a username.
EMAIL_DOMAIN = "contextguard.demo"

# Extended responsibilities the administrator explicitly does NOT get by default.
# Configuration authority is not financial-data authority.
ADMIN_DOES_NOT_IMPLY = [
    "restricted:view (requires an approved authorisation on the case)",
    "editing original transaction records",
    "approving their own access request",
]


# ── Synthetic demo accounts ──────────────────────────────────────────────────
#
# Passwords are demo-only and shown on the login page. In production these users
# would come from the bank's directory (OIDC/SAML) and this block would go away.

DEMO_USERS = [
    {
        "id": "u_analyst_1",
        "username": "analyst",
        "password": "analyst123",
        "name": "Ananya Iyer",
        "email": f"analyst@{EMAIL_DOMAIN}",
        "role": "analyst",
        "title": "Investigation Analyst",
        "assigned_case_ids": ["case_1", "case_2"],
    },
    {
        "id": "u_analyst_2",
        "username": "analyst2",
        "password": "analyst123",
        "name": "Rohit Deshmukh",
        "email": f"analyst2@{EMAIL_DOMAIN}",
        "role": "analyst",
        "title": "Investigation Analyst",
        "assigned_case_ids": ["case_3"],
    },
    {
        "id": "u_compliance_1",
        "username": "compliance",
        "password": "compliance123",
        "name": "Inspector R. Mehta",
        "email": f"compliance@{EMAIL_DOMAIN}",
        "role": "compliance",
        "title": "Compliance Officer",
        "assigned_case_ids": [],
    },
    {
        "id": "u_admin_1",
        "username": "admin",
        "password": "admin123",
        "name": "S. Nair",
        "email": f"admin@{EMAIL_DOMAIN}",
        "role": "admin",
        "title": "Organisation Administrator",
        "assigned_case_ids": [],
    },
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def permissions_for(role):
    """Return the (sorted) permission list for a role."""
    return sorted(ROLE_PERMISSIONS.get(role, set()))


def has_permission(role, permission):
    """True if the role holds a permission.

    Administrators do not bypass this check. Their set is the widest, but the
    permissions deliberately withheld from it — separation of duties around access
    requests, and everything gated on an authorisation — must actually stay withheld,
    otherwise "configuration authority is not financial-data access" would be a claim
    the server does not honour.
    """
    return permission in ROLE_PERMISSIONS.get(role, set())


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def public_user(user):
    """Strip secrets before a user document leaves the backend."""
    if not user:
        return None
    from config import ORGANIZATION

    meta = ROLE_META.get(user.get("role"), {})
    return {
        "id": user.get("id"),
        "username": user.get("username"),
        "name": user.get("name"),
        "email": user.get("email"),
        "role": user.get("role"),
        "role_code": meta.get("code", user.get("role")),
        "role_label": meta.get("label", user.get("role")),
        "responsibility": meta.get("responsibility"),
        "title": user.get("title"),
        "status": user.get("status", "active"),
        "assigned_case_ids": user.get("assigned_case_ids", []),
        "permissions": permissions_for(user.get("role")),
        "dashboard": meta.get("dashboard"),
        "organization": ORGANIZATION["name"],
        "organization_short": ORGANIZATION["short"],
        "environment": ORGANIZATION["environment"],
        "created_at": user.get("created_at"),
        "last_login": user.get("last_login"),
        "is_synthetic": user.get("is_synthetic", False),
    }


def find_user_by_identifier(db, identifier):
    """Resolve a login identifier that may be a username or an email address."""
    value = (identifier or "").strip().lower()
    if not value:
        return None
    return db.users.find_one({"$or": [{"username": value}, {"email": value}]})


# ── User storage ─────────────────────────────────────────────────────────────

def ensure_users(db):
    """Create the synthetic demo accounts, reconciling existing ones (idempotent).

    Reconciling matters because the demo accounts are part of the product surface:
    their email addresses are the documented login identifiers, so an older dataset
    must be brought up to date rather than left with stale addresses. Only accounts
    this service created are touched — never an operator's own.
    """
    created = []
    for spec in DEMO_USERS:
        existing = db.users.find_one({"username": spec["username"]})
        if existing:
            if existing.get("is_synthetic") and (
                existing.get("email") != spec["email"] or existing.get("name") != spec["name"]
                or existing.get("title") != spec["title"] or existing.get("role") != spec["role"]
            ):
                db.users.update_one({"username": spec["username"]}, {"$set": {
                    "email": spec["email"],
                    "name": spec["name"],
                    "title": spec["title"],
                    "role": spec["role"],
                }})
            continue
        db.users.insert_one({
            "id": spec["id"],
            "username": spec["username"],
            "password_hash": generate_password_hash(spec["password"]),
            "name": spec["name"],
            "email": spec["email"],
            "role": spec["role"],
            "title": spec["title"],
            "status": "active",
            "assigned_case_ids": list(spec.get("assigned_case_ids", [])),
            "failed_attempts": 0,
            "is_synthetic": True,
            "created_at": datetime.utcnow().isoformat(),
            "last_login": None,
        })
        created.append(spec["username"])
    return created


def ensure_case_assignments(db):
    """Give seeded/auto-created cases an owner so analyst scoping is demonstrable."""
    changed = []
    for spec in DEMO_USERS:
        for case_id in spec.get("assigned_case_ids", []):
            res = db.cases.update_one(
                {"id": case_id},
                {"$set": {"assigned_to": spec["id"], "assigned_to_name": spec["name"]}},
            )
            if res.modified_count:
                changed.append(case_id)

    # Analyst 2 owns any live-ingest case that has no owner yet.
    for case in db.cases.find({"assigned_to": {"$exists": False}}):
        if case.get("origin") == "live_ingest":
            db.cases.update_one(
                {"id": case["id"]},
                {"$set": {"assigned_to": "u_analyst_2", "assigned_to_name": "Rohit Deshmukh"}},
            )
    return changed


def get_user_by_username(db, username):
    return db.users.find_one({"username": (username or "").strip().lower()})


def get_user_by_email(db, email):
    return db.users.find_one({"email": (email or "").strip().lower()})


def get_user_by_id(db, user_id):
    return db.users.find_one({"id": user_id})


def list_users(db):
    return list(db.users.find().sort("created_at", 1))


def create_user(db, data):
    """Admin-created account. Returns (user, error)."""
    username = (data.get("username") or "").strip().lower()
    password = data.get("password") or ""
    role = data.get("role") or "analyst"

    email = (data.get("email") or "").strip().lower()
    if not username:
        return None, "Username is required"
    if len(password) < 8:
        return None, "Password must be at least 8 characters"
    if role not in ROLE_PERMISSIONS:
        return None, f"Unknown role: {role}"
    if db.users.find_one({"username": username}):
        return None, f"Username '{username}' already exists"
    if email and db.users.find_one({"email": email}):
        return None, f"Email '{email}' is already in use"

    user = {
        "id": f"u_{secrets.token_hex(6)}",
        "username": username,
        "password_hash": generate_password_hash(password),
        "name": (data.get("name") or username).strip(),
        "email": email,
        "role": role,
        "title": (data.get("title") or ROLE_META.get(role, {}).get("label", role)).strip(),
        "status": "active",
        "assigned_case_ids": list(data.get("assigned_case_ids") or []),
        "failed_attempts": 0,
        "is_synthetic": False,
        "created_at": datetime.utcnow().isoformat(),
        "last_login": None,
    }
    db.users.insert_one(user)
    return user, None


def update_user(db, user_id, data):
    """Admin update: role, status, assignment, password reset. Returns (user, error)."""
    user = get_user_by_id(db, user_id)
    if not user:
        return None, "User not found"

    updates = {}
    if "role" in data and data["role"]:
        if data["role"] not in ROLE_PERMISSIONS:
            return None, f"Unknown role: {data['role']}"
        updates["role"] = data["role"]
    if "status" in data and data["status"]:
        if data["status"] not in ("active", "suspended"):
            return None, "Status must be 'active' or 'suspended'"
        updates["status"] = data["status"]
    for field in ("name", "email", "title"):
        if field in data and data[field] is not None:
            value = str(data[field]).strip()
            if field == "email":
                value = value.lower()
                clash = db.users.find_one({"email": value, "id": {"$ne": user_id}})
                if value and clash:
                    return None, f"Email '{value}' is already in use"
            updates[field] = value
    if "assigned_case_ids" in data and data["assigned_case_ids"] is not None:
        updates["assigned_case_ids"] = list(data["assigned_case_ids"])
        # Keep the case documents in step with the assignment list.
        db.cases.update_many({"assigned_to": user_id}, {"$unset": {"assigned_to": "", "assigned_to_name": ""}})
        for case_id in updates["assigned_case_ids"]:
            db.cases.update_one(
                {"id": case_id},
                {"$set": {"assigned_to": user_id, "assigned_to_name": updates.get("name", user.get("name"))}},
            )
    if data.get("password"):
        if len(data["password"]) < 8:
            return None, "Password must be at least 8 characters"
        updates["password_hash"] = generate_password_hash(data["password"])

    if updates:
        db.users.update_one({"id": user_id}, {"$set": updates})
    # A role or status change invalidates existing sessions.
    if "role" in updates or "status" in updates or "password_hash" in updates:
        db.sessions.delete_many({"user_id": user_id})
    return get_user_by_id(db, user_id), None


def assign_case(db, case_id, user_id, assigned_by=None):
    """Assign (or clear) a case owner. Returns (case, error)."""
    case = db.cases.find_one({"id": case_id})
    if not case:
        return None, "Case not found"

    if not user_id:
        db.cases.update_one({"id": case_id}, {"$unset": {"assigned_to": "", "assigned_to_name": ""}})
        return db.cases.find_one({"id": case_id}), None

    user = get_user_by_id(db, user_id)
    if not user:
        return None, "Assignee not found"
    if user.get("role") != "analyst":
        return None, "Cases can only be assigned to analysts"

    previous = case.get("assigned_to")
    if previous and previous != user_id:
        db.users.update_one({"id": previous}, {"$pull": {"assigned_case_ids": case_id}})

    db.cases.update_one(
        {"id": case_id},
        {"$set": {"assigned_to": user_id, "assigned_to_name": user.get("name"), "assigned_by": assigned_by}},
    )
    db.users.update_one({"id": user_id}, {"$addToSet": {"assigned_case_ids": case_id}})
    return db.cases.find_one({"id": case_id}), None


# ── Sessions ─────────────────────────────────────────────────────────────────

def authenticate(db, username, password, timeout_minutes=DEFAULT_SESSION_MINUTES):
    """Verify credentials and mint a session token. Returns (user, token, error).

    `username` may be either the login name or the email address.
    """
    user = find_user_by_identifier(db, username)

    # Constant-ish response: never reveal whether the username exists.
    if not user or not check_password_hash(user.get("password_hash", ""), password or ""):
        if user:
            attempts = (user.get("failed_attempts") or 0) + 1
            update = {"failed_attempts": attempts}
            if attempts >= MAX_FAILED_ATTEMPTS:
                update["status"] = "suspended"
            db.users.update_one({"id": user["id"]}, {"$set": update})
        return None, None, "Invalid username or password"

    if user.get("status") == "suspended":
        return None, None, "This account is suspended. Contact your administrator."

    token = secrets.token_urlsafe(32)
    db.sessions.insert_one({
        "token_hash": hash_token(token),
        "user_id": user["id"],
        "issued_at": datetime.utcnow(),
        "expires_at": datetime.utcnow() + timedelta(minutes=timeout_minutes),
    })
    db.users.update_one(
        {"id": user["id"]},
        {"$set": {"last_login": datetime.utcnow().isoformat(), "failed_attempts": 0}},
    )
    return get_user_by_id(db, user["id"]), token, None


def resolve_session(db, token):
    """Return the user behind a token, or None if missing/expired/revoked."""
    if not token:
        return None
    session = db.sessions.find_one({"token_hash": hash_token(token)})
    if not session:
        return None
    if session.get("expires_at") and session["expires_at"] < datetime.utcnow():
        db.sessions.delete_one({"_id": session["_id"]})
        return None
    user = get_user_by_id(db, session["user_id"])
    if not user or user.get("status") != "active":
        return None
    return user


def revoke_session(db, token):
    if token:
        db.sessions.delete_one({"token_hash": hash_token(token)})
