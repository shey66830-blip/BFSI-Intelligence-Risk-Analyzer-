"""
Context Guard — Audit Trail

Every consequential action is appended to MongoDB with the acting identity. The log
is append-only from the API's point of view: routes can write and read it, never
edit or delete it.

An entry carries enough context to answer the question a supervisor actually asks —
who, did what, to which resource, with what result, and why.
"""

import hashlib
import json
import uuid
from datetime import datetime

# Canonical event vocabulary. Keeping it in one place stops the trail drifting
# into a hundred ad-hoc action strings.
EVENTS = {
    "login": "Login",
    "logout": "Logout",
    "login_failed": "Failed login",
    "view": "Resource viewed",
    "case_opened": "Case opened",
    "transaction_viewed": "Transaction viewed",
    "graph_viewed": "Graph viewed",
    "action": "Action performed",
    "evidence_added": "Evidence added",
    "evidence_accessed": "Evidence accessed",
    "evidence_updated": "Evidence reorganised",
    "report_created": "Analyst report created",
    "report_submitted": "Analyst report submitted",
    "report_amended": "Analyst report amended",
    "compliance_review": "Compliance review",
    "compliance_note": "Compliance note added",
    "update_posted": "Investigation update posted",
    "update_acknowledged": "Investigation update acknowledged",
    "access_request_created": "Access request created",
    "access_request_approved": "Access request approved",
    "access_request_rejected": "Access request rejected",
    "access_request_clarification": "Clarification requested",
    "access_statement_recorded": "Statement recorded",
    "bank_access_decision": "Bank decided an access request",
    "bank_gateway_awaiting": "Sent to the bank",
    "bank_gateway_failed": "Bank submission failed",
    "bank_response_deadline_expired": "Bank response deadline passed",
    "access_capability_granted": "Capability released",
    "restricted_accessed": "Restricted information accessed",
    "restricted_denied": "Restricted information refused",
    "access_expired": "Authorisation expired",
    "permission_changed": "Permission changed",
    "user_created": "User created",
    "user_disabled": "User disabled",
    "status_changed": "Case status changed",
    "decision": "Decision recorded",
    "access_denied": "Access denied",
    "system": "System event",
}


def record(db, user, action, target=None, detail=None, metadata=None, system=False,
           case_id=None, resource_type=None, resource_id=None, result="success", reason=None):
    """Append an audit entry.

    `user` is the acting identity (None for system events). `case_id` is set whenever
    the event touches an investigation, which is what makes per-case access history
    answerable.

    Every entry is hashed into a chain: it carries its sequence number, the hash of the
    entry before it, and its own hash over its own content. Editing an entry directly in
    the database therefore breaks the entry's own hash, and editing an entry *and* its
    hash breaks the next entry's — see `verify()`.
    """
    entry = {
        "id": f"aud_{uuid.uuid4().hex[:10]}",
        "action": action,
        "action_label": EVENTS.get(action, action),
        "target": target,
        "detail": detail,
        # Normalised to JSON at write time: the hash must be reproducible later, and a
        # caller that mutated its own metadata dict afterwards would otherwise leave a
        # stored hash that no longer describes the stored entry.
        "metadata": _normalise(metadata or {}),
        "timestamp": datetime.utcnow().isoformat(),
        "user_id": None if system else (user or {}).get("id"),
        "user": "System" if system else (user or {}).get("name", "Unknown"),
        "username": None if system else (user or {}).get("username"),
        "role": "system" if system else (user or {}).get("role", "unknown"),
        "case_id": case_id or (target if (target or "").startswith("case") else None),
        "resource_type": resource_type,
        "resource_id": resource_id if resource_id is not None else target,
        "result": result,
        "reason": reason,
    }
    _append_to_chain(db, entry)
    db.audit_log.insert_one(entry)
    return entry


# ── Tamper-evident chain ─────────────────────────────────────────────
#
# The trail is append-only *over the API*, but a process with write access to MongoDB
# could still edit it — which is exactly the move an insider makes. Each entry therefore
# carries its own hash and the hash of the entry before it, so an edit cannot be made
# without making the break detectable. This closes G-05 in SECURITY.md.

GENESIS = "0" * 64

# The fields whose content the hash covers. Anything not listed could change without
# breaking the chain, so the list is deliberately the whole entry's meaning rather than
# a convenient subset.
HASHED_FIELDS = (
    "seq", "action", "action_label", "target", "detail", "metadata", "timestamp",
    "user_id", "user", "username", "role", "case_id", "resource_type",
    "resource_id", "result", "reason", "prev_hash",
)


def _normalise(value):
    """Round-trip a value through JSON so it hashes and re-reads identically."""
    try:
        return json.loads(json.dumps(value, sort_keys=True, default=str))
    except (TypeError, ValueError):
        return json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)


def hash_entry(entry):
    """The hash of an entry's content, plus its link to the entry before it."""
    canonical = json.dumps(
        {field: _normalise(entry.get(field)) for field in HASHED_FIELDS},
        sort_keys=True, ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _ensure_chain(db):
    """Create the chain document, hashing anything written before the chain existed.

    Runs once, the first time anything is written after an upgrade, so an existing
    deployment is brought into the chain rather than starting part-way down it.
    """
    chain = db.audit_chain.find_one({"_id": "audit"})
    if chain:
        # A wiped log with a live chain would verify against a head nothing links to.
        # This is a fixture reset or an operator action, not a normal write, so it is
        # checked with an O(1) count rather than a query on every audit entry.
        if chain.get("seq") and db.audit_log.estimated_document_count() == 0:
            db.audit_chain.delete_one({"_id": "audit"})
            chain = None
        else:
            return chain

    head = GENESIS
    seq = 0
    for stored in db.audit_log.find({}).sort("_id", 1):
        entry = {k: v for k, v in stored.items() if k != "_id"}
        seq += 1
        entry["seq"] = seq
        entry["prev_hash"] = head
        digest = hash_entry(entry)
        db.audit_log.update_one({"_id": stored["_id"]}, {
            "$set": {"seq": seq, "prev_hash": head, "entry_hash": digest},
        })
        head = digest

    db.audit_chain.insert_one({
        "_id": "audit", "seq": seq, "head": head, "genesis": GENESIS,
        "created_at": datetime.utcnow().isoformat(),
    })
    return db.audit_chain.find_one({"_id": "audit"})


def _append_to_chain(db, entry):
    """Claim the next sequence number and link the entry to the current head.

    Uses a compare-and-swap on the chain head, so two concurrent writers cannot both
    claim the same link: the loser retries against the winner's head.
    """
    chain = _ensure_chain(db)
    for _ in range(5):
        seq, head = chain["seq"], chain["head"]
        entry["seq"] = seq + 1
        entry["prev_hash"] = head
        entry["entry_hash"] = hash_entry(entry)
        won = db.audit_chain.update_one(
            {"_id": "audit", "seq": seq, "head": head},
            {"$set": {"seq": seq + 1, "head": entry["entry_hash"],
                      "updated_at": datetime.utcnow().isoformat()}},
        )
        if won.modified_count == 1:
            return entry
        chain = db.audit_chain.find_one({"_id": "audit"})
        if not chain:
            chain = _ensure_chain(db)

    # Contended beyond any plausible concurrency: record the event rather than drop it,
    # and leave the gap for `verify()` to report.
    entry["seq"] = None
    entry["prev_hash"] = None
    entry["entry_hash"] = None
    return entry


def verify(db, limit=None):
    """Recompute the chain and report the first entry that does not reproduce.

    Returns whether every entry still hashes to what was stored, whether each entry links
    to the one before it, and — if not — where the break is. A break at entry *n* means
    that entry was edited, replaced, or inserted after the fact.
    """
    _ensure_chain(db)
    cursor = db.audit_log.find({}).sort("seq", 1)
    if limit:
        cursor = cursor.limit(limit)

    previous_hash = None
    previous_seq = None
    total = 0
    for entry in cursor:
        total += 1
        seq = entry.get("seq")
        if seq is None:
            return {"ok": False, "entries": total, "first_break": entry.get("id"),
                    "break_seq": None,
                    "reason": "an entry carries no sequence number"}
        if previous_seq is not None and seq != previous_seq + 1:
            return {"ok": False, "entries": total, "first_break": entry.get("id"),
                    "break_seq": seq,
                    "reason": f"sequence jumps from {previous_seq} to {seq} — an entry "
                              f"was removed or inserted"}
        if previous_seq is None and entry.get("prev_hash") != GENESIS:
            return {"ok": False, "entries": total, "first_break": entry.get("id"),
                    "break_seq": seq,
                    "reason": "the first entry does not start from the genesis hash"}
        if previous_seq is not None and entry.get("prev_hash") != previous_hash:
            return {"ok": False, "entries": total, "first_break": entry.get("id"),
                    "break_seq": seq,
                    "reason": "an entry does not link to its predecessor"}
        computed = hash_entry(entry)
        if entry.get("entry_hash") != computed:
            return {"ok": False, "entries": total, "first_break": entry.get("id"),
                    "break_seq": seq,
                    "reason": "an entry's content no longer matches its recorded hash — "
                              "it has been edited"}
        previous_hash = computed
        previous_seq = seq

    chain = db.audit_chain.find_one({"_id": "audit"}) or {}
    return {
        "ok": True, "entries": total, "first_break": None, "break_seq": None,
        "reason": "every entry reproduces its recorded hash and links to its predecessor",
        "head": previous_hash,
        "chain_head": chain.get("head"),
        "head_matches": previous_hash is None or chain.get("head") == previous_hash,
    }


def query(db, user_id=None, actions=None, limit=200, case_id=None, resource_id=None,
          result=None, offset=0):
    """Read the audit trail, newest first, one page at a time."""
    q = {}
    if user_id:
        q["user_id"] = user_id
    if case_id:
        q["case_id"] = case_id
    if resource_id:
        q["resource_id"] = resource_id
    if result:
        q["result"] = result
    if actions:
        q["action"] = {"$in": list(actions)}

    cursor = db.audit_log.find(q).sort("timestamp", -1).skip(max(0, offset or 0)).limit(limit)
    entries = list(cursor)
    for entry in entries:
        entry.pop("_id", None)
    return entries


def security_events(db, limit=12):
    """Authentication and authorisation events, for the admin dashboard."""
    return query(db, actions=[
        "login", "logout", "login_failed", "access_denied",
        "restricted_denied", "access_expired", "permission_changed",
    ], limit=limit)
