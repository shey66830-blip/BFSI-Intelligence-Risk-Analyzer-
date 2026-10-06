"""
Context Guard — Restricted Subject Information & Time-Limited Access

Access to a person's identifying and contact information is not a role privilege. It
is a separate, requested, justified and expiring authorisation.

The loop:

    compliance requests  →  admin approves / rejects / asks for clarification
                        →  an authorisation record with a scope and an expiry
                        →  the requester can see the covered categories until it lapses

Nothing here is granted permanently, nobody may approve their own request, and an
administrator holds configuration authority without holding financial-data authority —
so `restricted:view` is never part of any role, only of an authorisation.

Terminology is deliberate: a **subject** or **person of interest** whose information is
being reviewed. The system does not label anyone as a suspect, and every record states
that no determination of wrongdoing has been made.
"""

import uuid
from datetime import datetime, timedelta

from config import MAX_ACCESS_DURATION_DAYS, ORGANIZATION
from services import audit

# Categories of restricted information that may be requested individually.
CATEGORIES = [
    {"key": "identity", "label": "Identity Information",
     "description": "Legal name, date of birth, identity document references."},
    {"key": "contact", "label": "Contact Information",
     "description": "Registered telephone numbers, email addresses and addresses."},
    {"key": "documents", "label": "Supporting Images / Documents",
     "description": "Scanned documents and images held on file."},
    {"key": "external_reference", "label": "External Reference Information",
     "description": "Registry and external reference numbers held against the subject."},
    {"key": "investigator_notes", "label": "Investigator Notes",
     "description": "Case notes containing personal information."},
]

CATEGORY_KEYS = [c["key"] for c in CATEGORIES]

SUBJECT_LABELS = ("Investigation subject", "Person of interest")

DURATION_OPTIONS = [1, 3, 7, 14, 30]

NO_DETERMINATION_NOTICE = (
    "This record concerns an investigation subject. No determination of wrongdoing has "
    "been made, and inclusion here is not evidence of any offence."
)


def _now():
    return datetime.utcnow()


def _iso(dt):
    return dt.isoformat()


# ── Restricted subject information ───────────────────────────────────────────

def add_subject_information(db, case_id, payload):
    doc = {
        "id": f"RSI-{uuid.uuid4().hex[:8].upper()}",
        "case_id": case_id,
        "subject_id": payload.get("subject_id"),
        "subject_label": payload.get("subject_label") or "Investigation subject",
        "category": payload.get("category"),
        "title": payload.get("title"),
        "value": payload.get("value"),
        "source": payload.get("source") or "synthetic dataset",
        "classification": "restricted",
        "created_at": _iso(_now()),
        "notice": NO_DETERMINATION_NOTICE,
    }
    db.restricted_subject_information.insert_one(doc)
    return doc


def list_subject_information(db, case_id):
    return list(db.restricted_subject_information.find({"case_id": case_id}))


def vector(db, case_id):
    """Which categories exist for a case, with counts. Safe to show as a summary."""
    counts = {}
    for doc in db.restricted_subject_information.find({"case_id": case_id}):
        key = doc.get("category")
        counts[key] = counts.get(key, 0) + 1
    return {
        "case_id": case_id,
        "notice": NO_DETERMINATION_NOTICE,
        "categories": [
            {**spec, "records": counts.get(spec["key"], 0)}
            for spec in CATEGORIES
        ],
        "available": [k for k in CATEGORY_KEYS if counts.get(k)],
    }


def released(db, case_id, user, authorization):
    """Subject information the caller is authorised to see, with provenance."""
    categories = set(authorization.get("scope", []))
    records = []
    for doc in db.restricted_subject_information.find({
        "case_id": case_id, "category": {"$in": list(categories)}
    }):
        doc.pop("_id", None)
        doc["authorization"] = {
            "request_id": authorization.get("request_id"),
            "authorization_id": authorization.get("id"),
            "approved_by": authorization.get("approved_by_name"),
            "approved_at": authorization.get("approved_at"),
            "expires_at": authorization.get("expires_at"),
            "scope": authorization.get("scope"),
            "reason": authorization.get("reason"),
        }
        # The same account of origin the bank releases carry, so a restricted record and
        # a bank-released record are traceable in the same way.
        doc["provenance"] = {
            "origin": "bank_release",
            "origin_label": "released under an access authorisation",
            "case_id": case_id,
            "category": doc.get("category"),
            "request_id": authorization.get("request_id"),
            "authorization_id": authorization.get("id"),
            "released_by": authorization.get("approved_by_name"),
            "decider_type": authorization.get("decider_type"),
            "released_at": authorization.get("approved_at"),
            "released_to": authorization.get("granted_to_name"),
            "expires_at": authorization.get("expires_at"),
            "stated_purpose": authorization.get("reason"),
        }
        records.append(doc)
    return records


# ── Authorisations ───────────────────────────────────────────────────────────

def active_authorization(db, user_id, case_id, category=None):
    """The authorisation covering this user, case and category right now, if any.

    Timestamps are stored as ISO-8601 UTC strings throughout, and compared as such:
    mixing a string field with a datetime in a query compares BSON types, not values,
    so an authorisation would never match and every read would look expired.
    """
    query = {
        "granted_to": user_id,
        "case_id": case_id,
        "revoked_at": None,
        "expires_at": {"$gt": _iso(_now())},
    }
    candidates = list(db.access_authorizations.find(query).sort("expires_at", -1))
    for auth in candidates:
        if category is None or category in (auth.get("scope") or []):
            auth.pop("_id", None)
            return auth
    return None


def expired_authorization(db, user_id, case_id):
    """A previously granted authorisation that has now lapsed, for the UI's 🔒 state."""
    auth = db.access_authorizations.find_one(
        {"granted_to": user_id, "case_id": case_id,
         "expires_at": {"$lte": _iso(_now())}},
        sort=[("expires_at", -1)],
    )
    if auth:
        auth.pop("_id", None)
    return auth


def restricted_access(db, user, case_id, category=None):
    """The single gate every restricted read goes through.

    Returns (allowed, authorization_or_reason, reason). Administrators are NOT exempt:
    configuration authority is not financial-data authority.
    """
    auth = active_authorization(db, user["id"], case_id, category)
    if auth:
        return True, auth, None

    expired = expired_authorization(db, user["id"], case_id)
    if expired:
        return False, None, (f"Access expired on {str(expired.get('expires_at'))[:16]}. "
                             f"Submit a new request if the information is still required.")

    pending = db.access_requests.find_one({
        "case_id": case_id, "requested_by": user["id"], "status": "pending",
    })
    if pending:
        return False, None, f"Request {pending['id']} is pending administrator approval."

    return False, None, ("Restricted subject information requires an approved access request "
                         "for this case.")


def expire_stale(db):
    """Lazily mark lapsed requests/authorisations. Returns how many changed."""
    now = _iso(_now())
    auths = db.access_authorizations.update_many(
        {"expires_at": {"$lte": now}, "revoked_at": None, "expired_marked": {"$ne": True}},
        {"$set": {"expired_marked": True, "expired_at": now}},
    )
    requests = db.access_requests.update_many(
        {"status": "approved", "expires_at": {"$lte": now}},
        {"$set": {"status": "expired", "updated_at": now}},
    )
    # The bank gateway owns the other clock: it delivers any answer that has come due and
    # lapses a request the bank never answered by its response deadline.
    from services import bank_gateway
    _, lapsed = bank_gateway.sweep(db)
    return auths.modified_count, requests.modified_count + lapsed


# ── Requests ─────────────────────────────────────────────────────────────────

def create_request(db, case, user, payload):
    """Create a request. Returns (request, error)."""
    categories = payload.get("categories") or ([payload["category"]] if payload.get("category") else [])
    categories = [c for c in categories if c in CATEGORY_KEYS]
    if not categories:
        return None, "Select at least one category of restricted information"
    if not (payload.get("reason") or "").strip():
        return None, "A reason for the request is required"
    if not (payload.get("necessity") or "").strip():
        return None, "Explain why the information is necessary for the investigation"

    try:
        duration = int(payload.get("duration_days") or 7)
    except (TypeError, ValueError):
        return None, "Duration must be a number of days"
    if duration < 1 or duration > MAX_ACCESS_DURATION_DAYS:
        return None, f"Duration must be between 1 and {MAX_ACCESS_DURATION_DAYS} days"

    # One open request at a time *for the same thing*: a pending request for bank-held
    # records says nothing about a request for organisation-held capabilities, because
    # different parties decide them.
    open_request = db.access_requests.find_one({
        "case_id": case["id"], "requested_by": user["id"],
        "target": "subject_information",
        "status": {"$in": ["pending", "clarification_requested"]},
    })
    if open_request:
        return None, f"Request {open_request['id']} for this case is already awaiting a decision"

    request = {
        "id": f"REQ-{uuid.uuid4().hex[:6].upper()}",
        "target": "subject_information",
        "case_id": case["id"],
        "case_title": case.get("title"),
        "requested_by": user["id"],
        "requested_by_name": user["name"],
        "requested_by_role": user["role"],
        "requested_by_email": user.get("email"),
        "categories": categories,
        "category_labels": [dict((c["key"], c["label"]) for c in CATEGORIES)[k] for k in categories],
        "reason": payload["reason"].strip(),
        "necessity": payload["necessity"].strip(),
        "related_finding": (payload.get("related_finding") or "").strip(),
        "duration_days": duration,
        "status": "pending",
        "created_at": _iso(_now()),
        "updated_at": _iso(_now()),
        "decision": None,
        "authorization_id": None,
        "expires_at": None,
        "organization": ORGANIZATION["name"],
        "notice": NO_DETERMINATION_NOTICE,
    }
    db.access_requests.insert_one(request)
    request.pop("_id", None)
    return request, None


def get_request(db, request_id):
    doc = db.access_requests.find_one({"id": request_id})
    if doc:
        doc.pop("_id", None)
    return doc


def list_requests(db, requester_id=None, case_ids=None, statuses=None, limit=200):
    q = {}
    if requester_id:
        q["requested_by"] = requester_id
    if case_ids is not None:
        q["case_id"] = {"$in": list(case_ids)}
    if statuses:
        q["status"] = {"$in": list(statuses)}
    out = list(db.access_requests.find(q).sort("created_at", -1).limit(limit))
    now = _now()
    for doc in out:
        doc.pop("_id", None)
        if doc.get("status") == "approved" and doc.get("expires_at"):
            if str(doc["expires_at"]) <= _iso(now):
                doc["status"] = "expired"
    return out


def request_for_update(db, request_id, user, status, reason=None, note=None,
                       duration_days=None, scope=None):
    """Approve / reject / request clarification. Returns (request, authorization, error)."""
    request = get_request(db, request_id)
    if not request:
        return None, None, "Request not found"

    if request["requested_by"] == user["id"]:
        return None, None, ("You cannot decide your own access request — a different "
                            "administrator must review it")
    if request["status"] not in ("pending", "clarification_requested"):
        return None, None, f"Request {request_id} is already {request['status']}"

    now = _now()
    update = {"updated_at": _iso(now)}

    if status == "clarification_requested":
        if not (note or "").strip():
            return None, None, "Explain what clarification is needed"
        update.update({
            "status": "clarification_requested",
            "decision": {"by": user["id"], "by_name": user["name"], "at": _iso(now),
                         "outcome": "clarification_requested", "note": note.strip()},
        })
        db.access_requests.update_one({"id": request_id}, {"$set": update})
        return get_request(db, request_id), None, None

    if status == "rejected":
        if not (reason or "").strip():
            return None, None, "A rejection reason is required"
        update.update({
            "status": "rejected",
            "decision": {"by": user["id"], "by_name": user["name"], "at": _iso(now),
                         "outcome": "rejected", "reason": reason.strip()},
        })
        db.access_requests.update_one({"id": request_id}, {"$set": update})
        return get_request(db, request_id), None, None

    if status != "approved":
        return None, None, f"Unknown decision: {status}"

    # A request for a locked capability is released the same way whichever party granted
    # it: an authorisation that names the capability, the scope and the expiry.
    if request.get("kind") == "locked_item":
        try:
            days = int(duration_days or request.get("duration_days") or 7)
        except (TypeError, ValueError):
            return None, None, "Duration must be a number of days"
        if days < 1 or days > MAX_ACCESS_DURATION_DAYS:
            return None, None, f"Duration must be between 1 and {MAX_ACCESS_DURATION_DAYS} days"
        granted = [k for k in (scope or request.get("resource_keys") or []) if k in RESOURCE_BY_KEY]
        if not granted:
            return None, None, "The approved scope must include at least one locked item"
        scoped = {**request, "resource_keys": granted}
        authorization = build_authorization(db, scoped, user, "admin", note=note, days=days)
        db.access_requests.update_one({"id": request_id}, {"$set": {
            "updated_at": _iso(now),
            "status": "approved",
            "authorization_id": authorization["id"],
            "expires_at": authorization["expires_at"],
            "decision": {"by": user["id"], "by_name": user["name"], "at": _iso(now),
                         "outcome": "approved", "duration_days": days, "scope": granted,
                         "note": note},
        }})
        return get_request(db, request_id), authorization, None

    days = duration_days or request.get("duration_days") or 7
    try:
        days = int(days)
    except (TypeError, ValueError):
        return None, None, "Duration must be a number of days"
    if days < 1 or days > MAX_ACCESS_DURATION_DAYS:
        return None, None, f"Duration must be between 1 and {MAX_ACCESS_DURATION_DAYS} days"

    granted_scope = scope or request.get("categories") or []
    granted_scope = [c for c in granted_scope if c in CATEGORY_KEYS]
    if not granted_scope:
        return None, None, "The approved scope must include at least one category"

    authorization = {
        "id": f"AUTH-{uuid.uuid4().hex[:6].upper()}",
        "request_id": request["id"],
        "case_id": request["case_id"],
        "case_title": request.get("case_title"),
        "granted_to": request["requested_by"],
        "granted_to_name": request.get("requested_by_name"),
        "granted_to_role": request.get("requested_by_role"),
        "approved_by": user["id"],
        "approved_by_name": user["name"],
        "approved_at": _iso(now),
        "scope": granted_scope,
        "scope_labels": [dict((c["key"], c["label"]) for c in CATEGORIES)[k]
                         for k in granted_scope],
        "revoked_scope": [c for c in (request.get("categories") or []) if c not in granted_scope],
        "starts_at": _iso(now),
        "expires_at": _iso(now + timedelta(days=days)),
        "duration_days": days,
        "reason": request.get("reason"),
        "necessity": request.get("necessity"),
        "revoked_at": None,
        "organization": ORGANIZATION["name"],
        "notice": NO_DETERMINATION_NOTICE,
        "conditions": ("Time-limited and case-scoped. Access ends automatically at expiry and "
                       "each read is recorded in the audit trail."),
    }
    db.access_authorizations.insert_one(authorization)

    update.update({
        "status": "approved",
        "authorization_id": authorization["id"],
        "expires_at": authorization["expires_at"],
        "decision": {"by": user["id"], "by_name": user["name"], "at": _iso(now),
                     "outcome": "approved", "duration_days": days, "scope": granted_scope,
                     "note": note},
    })
    db.access_requests.update_one({"id": request_id}, {"$set": update})
    authorization.pop("_id", None)
    return get_request(db, request_id), authorization, None


def revoke(db, authorization_id, user, reason=None):
    doc = db.access_authorizations.find_one({"id": authorization_id})
    if not doc:
        return None, "Authorisation not found"
    db.access_authorizations.update_one({"id": authorization_id}, {"$set": {
        "revoked_at": _iso(_now()), "revoked_by": user["id"],
        "revoked_by_name": user["name"], "revoke_reason": reason,
    }})
    doc.pop("_id", None)
    return doc, None


def list_authorizations(db, case_id=None, user_id=None, active_only=False, limit=200):
    q = {}
    if case_id:
        q["case_id"] = case_id
    if user_id:
        q["granted_to"] = user_id
    if active_only:
        q["expires_at"] = {"$gt": _iso(_now())}
        q["revoked_at"] = None
    out = list(db.access_authorizations.find(q).sort("approved_at", -1).limit(limit))
    for doc in out:
        doc.pop("_id", None)
        doc["is_active"] = (not doc.get("revoked_at")) and str(doc.get("expires_at")) > _iso(_now())
    return out


def expiry_label(authorization):
    """Human-readable remaining time, used by the UI's authorisation banner."""
    if not authorization:
        return None
    try:
        expires = datetime.fromisoformat(str(authorization["expires_at"]))
    except (KeyError, ValueError):
        return None
    remaining = expires - _now()
    if remaining.total_seconds() <= 0:
        return "expired"
    hours = int(remaining.total_seconds() // 3600)
    if hours < 24:
        return f"{hours}h remaining"
    return f"{hours // 24}d remaining"


# ── Locked features and information ─────────────────────────────────────────
#
# Not every gate is a role gate. Some capabilities and some records are withheld
# from analyst *and* compliance alike, because releasing them is not a role
# privilege — it is a decision somebody else has to make, state a reason for, and
# answer for afterwards.
#
# Every entry names who can release it:
#
#   bank   — only the bank that holds the record can, because the platform never
#            holds it in the first place (services/bank_review.py stands in for it)
#   admin  — an organisation administrator releases it on the organisation's behalf
#
# `unlocks` are permissions released *while* an authorisation is live, so a release
# is a capability rather than a role: it starts, it expires and every use is
# recorded. Nothing here is ever added to ROLE_PERMISSIONS.

MIN_STATEMENT_WORDS = 25

LOCKED_RESOURCES = [
    {
        "key": "bank_ledger_detail", "track": "bank",
        "label": "Bank ledger detail",
        "description": ("The statement lines behind the summary the bank returned — held by the "
                        "bank and never copied into the platform."),
        "unlocks": ["restricted:view"],
        "unlock_label": "the bank's ledger extract for this case",
    },
    {
        "key": "bank_counterparty_detail", "track": "bank",
        "label": "Counterparty detail",
        "description": "Who the counterparty is on the bank's own records, and where the funds moved from.",
        "unlocks": ["restricted:view"],
        "unlock_label": "counterparty detail as the bank records it",
    },
    {
        "key": "bank_beneficial_ownership", "track": "bank",
        "label": "Beneficial ownership on file",
        "description": "The ownership declarations and registry references the bank holds against the entity.",
        "unlocks": ["restricted:view"],
        "unlock_label": "the bank's beneficial ownership file",
    },
    {
        "key": "bank_source_of_funds", "track": "bank",
        "label": "Source-of-funds declaration",
        "description": "What the customer told the bank about where the money came from, in the bank's words.",
        "unlocks": ["restricted:view"],
        "unlock_label": "the bank's source-of-funds declaration",
    },
    {
        "key": "unmasked_identifiers", "track": "admin",
        "label": "Unmasked customer identifiers",
        "description": "Real names and account identifiers rather than the masked view your role is given.",
        "unlocks": ["txn:view_unmasked"],
        "unlock_label": "unmasked identifiers on the cases you can already open",
    },
    {
        "key": "cross_bank_network", "track": "admin",
        "label": "Cross-bank network graph",
        "description": "The whole relationship graph, not only the entities reachable from your own cases.",
        "unlocks": ["graph:view_all"],
        "unlock_label": "the organisation-wide relationship graph",
    },
    {
        "key": "vault_curation", "track": "admin",
        "label": "Evidence vault curation",
        "description": "Reorganise the vault — folder, status and access level — rather than only filing into it.",
        "unlocks": ["evidence:manage"],
        "unlock_label": "the evidence vault's curation controls",
    },
]

RESOURCE_BY_KEY = {r["key"]: r for r in LOCKED_RESOURCES}
RESOURCE_KEYS = [r["key"] for r in LOCKED_RESOURCES]

TRACK_DECIDER = {
    "bank": "the bank holding the record",
    "admin": "an organisation administrator",
}

STATEMENT_LABELS = {
    "requester_statement": "Requester's statement",
    "bank_statement": "Bank's statement",
    "administrator_statement": "Administrator's statement",
}


def resource_state(db, case_id, user_id, resource_key):
    """Where this caller stands on one locked item. Returns (state, document)."""
    now = _iso(_now())
    for auth in db.access_authorizations.find({
            "granted_to": user_id, "case_id": case_id, "revoked_at": None,
            "expires_at": {"$gt": now}}):
        if resource_key in (auth.get("resources") or []):
            return "granted", auth
    for request_doc in db.access_requests.find({
            "case_id": case_id, "requested_by": user_id,
            "status": {"$in": ["pending", "clarification_requested", "awaiting_bank"]}},
            sort=[("updated_at", -1)]):
        if resource_key in (request_doc.get("resource_keys") or []):
            # A request that is out with the bank is not the same as one waiting on a
            # person, so it keeps its own state rather than collapsing into `pending`.
            state = "awaiting_bank" if request_doc.get("status") == "awaiting_bank" else "pending"
            return state, request_doc
    for auth in db.access_authorizations.find({
            "granted_to": user_id, "case_id": case_id, "revoked_at": None,
            "expires_at": {"$lte": now}}, sort=[("expires_at", -1)]):
        if resource_key in (auth.get("resources") or []):
            return "expired", auth
    # A request the bank never answered inside its window has lapsed, not been refused.
    for request_doc in db.access_requests.find({
            "case_id": case_id, "requested_by": user_id, "status": "expired"},
            sort=[("updated_at", -1)]):
        if resource_key in (request_doc.get("resource_keys") or []):
            return "expired", request_doc
    for request_doc in db.access_requests.find({
            "case_id": case_id, "requested_by": user_id,
            "status": {"$in": ["rejected", "partially_approved"]}},
            sort=[("updated_at", -1)]):
        keys = request_doc.get("resource_keys") or []
        refused = request_doc.get("refused_keys")
        # A partial approval only refuses the items the bank named; the rest were granted
        # and are reported by the authorisation lookup above.
        if refused is not None and resource_key not in refused:
            continue
        if resource_key in keys:
            return "rejected", request_doc
    return "locked", None


def catalogue(db, case_id, user):
    """Every locked item, this caller's state on it, and who would decide."""
    items = []
    for spec in LOCKED_RESOURCES:
        state, doc = resource_state(db, case_id, user["id"], spec["key"])
        item = {
            "key": spec["key"], "label": spec["label"], "track": spec["track"],
            "description": spec["description"], "unlocks": spec["unlocks"],
            "unlock_label": spec["unlock_label"],
            "decider": TRACK_DECIDER[spec["track"]],
            "state": state,
        }
        if state == "granted" and doc:
            item["authorization"] = {
                key: doc.get(key) for key in
                ("id", "request_id", "expires_at", "approved_by_name", "decider_type", "unlock_labels")
            }
            item["remaining"] = expiry_label(doc)
        elif doc:
            item["request_id"] = doc.get("id")
            item["request_status"] = doc.get("status")
            decision = doc.get("decision") or doc.get("bank_decision") or {}
            item["decision_reason"] = decision.get("reason") or decision.get("statement")
            item["decided_by"] = (decision.get("by_name") or decision.get("reviewer"))
            # While a bank-held request is out, the item carries the bank's window so the
            # interface can say how long the answer has.
            if doc.get("status") == "awaiting_bank":
                item["respond_at"] = doc.get("respond_at")
                item["response_deadline"] = doc.get("response_deadline")
                item["bank_error"] = doc.get("bank_error")
        items.append(item)
    return items


def record_statement(db, actor, request_doc, kind, text, metadata=None):
    """Append a statement to the request and to the audit trail.

    Statements are evidence in their own right, so they are recorded whether or not
    any screen renders them. They are readable in the request record and the audit
    trail, and nowhere else.
    """
    text = (text or "").strip()
    if not text:
        return None
    entry = {
        "kind": kind,
        "label": STATEMENT_LABELS.get(kind, kind),
        "text": text,
        "author_id": (actor or {}).get("id"),
        "author_name": (actor or {}).get("name", "Unknown"),
        "author_role": (actor or {}).get("role", "system"),
        "at": _iso(_now()),
    }
    db.access_requests.update_one({"id": request_doc["id"]}, {
        "$push": {"statements": entry},
        "$set": {"updated_at": _iso(_now()),
                 "statement_count": (request_doc.get("statement_count") or 0) + 1},
    })
    # The full text goes to the trail even when the interface never shows it.
    audit.record(db, actor, "access_statement_recorded", target=request_doc["id"],
                 case_id=request_doc.get("case_id"), resource_type="access_request",
                 resource_id=request_doc["id"],
                 detail=f"{entry['label']} on {request_doc['id']}: {text}",
                 metadata={"kind": kind, "recorded_only": True, **(metadata or {})})
    return entry


def active_unlocks(db, user_id):
    """Capabilities released to this identity by an authorisation that is live now."""
    unlocks = set()
    for auth in db.access_authorizations.find({
            "granted_to": user_id, "revoked_at": None,
            "expires_at": {"$gt": _iso(_now())}}):
        unlocks.update(auth.get("unlocks") or [])
    return unlocks


def create_resource_request(db, case, user, payload):
    """A request for a locked feature or a bank-held record. Returns (request, error)."""
    keys = [k for k in (payload.get("resource_keys") or []) if k in RESOURCE_BY_KEY]
    if not keys:
        return None, "Select at least one locked item"

    statement = (payload.get("statement") or "").strip()
    if len(statement.split()) < MIN_STATEMENT_WORDS:
        return None, (f"A statement of at least {MIN_STATEMENT_WORDS} words is required: say what "
                      f"the information is needed for, and why it cannot be obtained another way")

    tracks = {RESOURCE_BY_KEY[k]["track"] for k in keys}
    if len(tracks) > 1:
        return None, ("Bank-held records and organisation-held capabilities are decided by "
                      "different parties — submit them as separate requests")

    try:
        duration = int(payload.get("duration_days") or 7)
    except (TypeError, ValueError):
        return None, "Duration must be a number of days"
    if duration < 1 or duration > MAX_ACCESS_DURATION_DAYS:
        return None, f"Duration must be between 1 and {MAX_ACCESS_DURATION_DAYS} days"

    track = tracks.pop()
    open_request = db.access_requests.find_one({
        "case_id": case["id"], "requested_by": user["id"],
        "target": f"locked:{track}",
        "status": {"$in": ["pending", "clarification_requested"]}})
    if open_request:
        return None, (f"Request {open_request['id']} for this case is already awaiting a "
                      f"decision on {TRACK_DECIDER[track]}")

    request_doc = {
        "id": f"REQ-{uuid.uuid4().hex[:6].upper()}",
        "kind": "locked_item",
        "target": f"locked:{track}",
        "case_id": case["id"],
        "case_title": case.get("title"),
        "requested_by": user["id"],
        "requested_by_name": user["name"],
        "requested_by_role": user["role"],
        "requested_by_email": user.get("email"),
        "resource_keys": keys,
        "resource_labels": [RESOURCE_BY_KEY[k]["label"] for k in keys],
        "categories": [],
        "category_labels": [],
        "track": track,
        "decider": TRACK_DECIDER[track],
        "statement": statement,
        "reason": statement,
        "necessity": (payload.get("necessity") or "").strip() or statement,
        "related_finding": (payload.get("related_finding") or "").strip(),
        "duration_days": duration,
        "status": "pending",
        "statements": [],
        "statement_count": 0,
        "created_at": _iso(_now()),
        "updated_at": _iso(_now()),
        "decision": None,
        "bank_decision": None,
        "authorization_id": None,
        "expires_at": None,
        "organization": ORGANIZATION["name"],
        "notice": NO_DETERMINATION_NOTICE,
    }
    db.access_requests.insert_one(request_doc)
    record_statement(db, user, request_doc, "requester_statement", statement,
                     {"resources": keys, "duration_days": duration})
    return get_request(db, request_doc["id"]), None


def build_authorization(db, request_doc, decider, decider_type, note=None, days=None, keys=None):
    """The authorisation a granted request produces, with the capability it releases.

    `keys` narrows what is released: a bank may approve part of what was asked for, and
    the authorisation then covers only that part.
    """
    keys = (request_doc.get("resource_keys") if keys is None else keys) or []
    keys = [k for k in keys if k in RESOURCE_BY_KEY]
    days = int(days or request_doc.get("duration_days") or 7)
    now = _now()
    authorization = {
        "id": f"AUTH-{uuid.uuid4().hex[:6].upper()}",
        "request_id": request_doc["id"],
        "case_id": request_doc["case_id"],
        "case_title": request_doc.get("case_title"),
        "granted_to": request_doc["requested_by"],
        "granted_to_name": request_doc.get("requested_by_name"),
        "granted_to_role": request_doc.get("requested_by_role"),
        "approved_by": decider["id"],
        "approved_by_name": decider["name"],
        "approved_by_role": decider.get("role"),
        "decider_type": decider_type,
        "approved_at": _iso(now),
        "scope": keys,
        "scope_labels": [RESOURCE_BY_KEY[k]["label"] for k in keys],
        "resources": keys,
        "unlocks": sorted({u for k in keys for u in RESOURCE_BY_KEY[k]["unlocks"]}),
        "unlock_labels": sorted({RESOURCE_BY_KEY[k]["unlock_label"] for k in keys}),
        "revoked_scope": [],
        "starts_at": _iso(now),
        "expires_at": _iso(now + timedelta(days=days)),
        "duration_days": days,
        "reason": request_doc.get("reason"),
        "statement": request_doc.get("statement"),
        "revoked_at": None,
        "organization": ORGANIZATION["name"],
        "notice": NO_DETERMINATION_NOTICE,
        "conditions": ("Case-scoped, time-limited and recorded. The capability lapses by itself at "
                       "expiry, and every use of it is written to the audit trail."),
    }
    if note:
        authorization["decision_note"] = note
    db.access_authorizations.insert_one(authorization)
    authorization.pop("_id", None)
    return authorization


def settle_bank_request(db, request_doc, decision, bank_identity):
    """Apply the bank's own decision to a bank-held request. Returns (request, authorisation).

    The bank can approve the request in whole, approve part of it and refuse the rest, or
    refuse it. A partial approval still produces an authorisation — over exactly the items
    the bank released.
    """
    status = decision["outcome"]
    update = {"updated_at": _iso(_now()), "bank_decision": decision, "status": status,
              "respond_at": None, "bank_error": None}
    authorization = None
    if status in ("approved", "partially_approved"):
        approved = decision.get("approved_keys")
        authorization = build_authorization(
            db, request_doc, bank_identity, "bank", note=decision.get("statement"),
            keys=(approved if approved is not None else request_doc.get("resource_keys")))
        update.update({"authorization_id": authorization["id"],
                       "expires_at": authorization["expires_at"]})
    refused = decision.get("refused_keys")
    if refused:
        update["refused_keys"] = refused
    db.access_requests.update_one({"id": request_doc["id"]}, {"$set": update})
    record_statement(db, bank_identity, request_doc, "bank_statement", decision["statement"],
                     {"outcome": status, "reasons": decision.get("reasons"),
                      "approved_keys": decision.get("approved_keys"),
                      "refused_keys": decision.get("refused_keys")})
    return get_request(db, request_doc["id"]), authorization
