"""
Context Guard — Investigation Notes & Transaction Relevance

Two analyst capabilities that the report is built from:

* **Notes** are the analyst's own working record on a case — an observation, an open
  question, a recommended next step. They are deliberately not a chat channel: each
  note has a kind, an author and a resolution state, and only the note that carries
  a finding is promoted into the investigation report.
* **Relevance marks** record which transactions the analyst considers material to the
  case, with a reason. Marking is an annotation *about* a transaction — the original
  financial record is never touched, which is the guarantee the role matrix makes to
  the analyst and to the audit trail.

Notes and marks are append-only in spirit: a note is resolved rather than deleted, and
a changed mark keeps its previous value in `history`.
"""

import uuid
from datetime import datetime

# The kind of note decides who is told about it. An observation is for the analyst's
# own file and compliance's queue; a compliance note is a question back to the analyst.
NOTE_KINDS = {
    "observation": {
        "label": "Observation",
        "description": "Something the analyst has established from the evidence.",
        "audience": ["compliance", "admin"],
    },
    "question": {
        "label": "Open question",
        "description": "Something the evidence does not yet answer.",
        "audience": ["compliance", "admin"],
    },
    "next_step": {
        "label": "Recommended next step",
        "description": "What the analyst proposes to do or to ask a bank for.",
        "audience": ["compliance", "admin"],
    },
    "compliance_note": {
        "label": "Compliance note",
        "description": "A review note or clarification request from the compliance officer.",
        "audience": ["analyst", "admin"],
    },
}

RELEVANCE_REASONS = [
    "primary transaction under review",
    "part of the same pattern",
    "beneficiary or counterparty link",
    "supports the legitimate explanation",
    "contradicts the legitimate explanation",
    "historical behaviour baseline",
]


def _now():
    return datetime.utcnow().isoformat()


# ── Notes ────────────────────────────────────────────────────────────────────

def add_note(db, case, user, data):
    """Add a working note to a case. Returns (note, error)."""
    kind = (data.get("kind") or "observation").strip().lower()
    body = (data.get("body") or "").strip()

    if kind not in NOTE_KINDS:
        return None, f"Unknown note kind: {kind}"
    if len(body) < 3:
        return None, "A note needs some content"
    if len(body) > 4000:
        return None, "A note is limited to 4000 characters"

    # A compliance note is a reviewer talking to the analyst; the other kinds are the
    # analyst talking to compliance. Recording the wrong direction would misroute it.
    if kind == "compliance_note" and user.get("role") == "analyst":
        return None, "Compliance notes are recorded by a compliance officer or administrator"

    note = {
        "id": f"NOTE-{uuid.uuid4().hex[:8].upper()}",
        "case_id": case["id"],
        "case_title": case.get("title"),
        "kind": kind,
        "kind_label": NOTE_KINDS[kind]["label"],
        "body": body,
        "transaction_id": data.get("transaction_id") or None,
        "evidence_ids": list(data.get("evidence_ids") or []),
        "author_id": user["id"],
        "author_name": user["name"],
        "author_role": user.get("role"),
        "created_at": _now(),
        "resolved_by": None,
        "resolved_by_name": None,
        "resolved_at": None,
        "resolution": None,
        "history": [],
    }
    db.case_notes.insert_one(note)
    note.pop("_id", None)
    return note, None


def list_notes(db, case_id, kind=None, include_resolved=True, limit=200):
    q = {"case_id": case_id}
    if kind and kind != "all":
        q["kind"] = kind
    if not include_resolved:
        q["resolved_at"] = None
    notes = list(db.case_notes.find(q).sort("created_at", -1).limit(limit))
    for note in notes:
        note.pop("_id", None)
    return notes


def get_note(db, note_id):
    return db.case_notes.find_one({"id": note_id})


def resolve_note(db, note, user, resolution=None):
    """Close an open question or next step without removing the note."""
    db.case_notes.update_one(
        {"id": note["id"]},
        {
            "$set": {
                "resolved_by": user["id"],
                "resolved_by_name": user["name"],
                "resolved_at": _now(),
                "resolution": (resolution or "").strip() or None,
            }
        },
    )
    updated = db.case_notes.find_one({"id": note["id"]})
    updated.pop("_id", None)
    return updated


def note_counts(db, case_id):
    return {
        "total": db.case_notes.count_documents({"case_id": case_id}),
        "open_questions": db.case_notes.count_documents(
            {"case_id": case_id, "kind": "question", "resolved_at": None}),
        "open_next_steps": db.case_notes.count_documents(
            {"case_id": case_id, "kind": "next_step", "resolved_at": None}),
        "compliance_notes": db.case_notes.count_documents(
            {"case_id": case_id, "kind": "compliance_note"}),
    }


# ── Transaction relevance ────────────────────────────────────────────────────

def set_relevance(db, case, user, transaction_id, relevant, reason=None):
    """Mark or clear a transaction's relevance to a case. Returns (record, error).

    The transaction row itself is never written to — only this annotation is, so an
    analyst action cannot alter the financial record.
    """
    case_entity_ids = set(case.get("entity_ids") or [])
    txn = db.transactions.find_one({"transaction_id": transaction_id})
    if not txn:
        return None, "Transaction not found"
    if case_entity_ids and txn.get("entity_id") not in case_entity_ids:
        return None, "That transaction does not belong to this case"

    existing = db.case_transaction_relevance.find_one(
        {"case_id": case["id"], "transaction_id": transaction_id})

    if not relevant:
        if not existing:
            return None, "That transaction is not marked as relevant"
        db.case_transaction_relevance.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "relevant": False,
                    "cleared_by": user["id"],
                    "cleared_by_name": user["name"],
                    "cleared_at": _now(),
                    "reason": (reason or "").strip() or existing.get("reason"),
                },
                "$push": {
                    "history": {
                        "relevant": False,
                        "by": user["name"],
                        "role": user.get("role"),
                        "reason": (reason or "").strip() or None,
                        "at": _now(),
                    }
                },
            },
        )
        record = db.case_transaction_relevance.find_one(
            {"case_id": case["id"], "transaction_id": transaction_id})
        record.pop("_id", None)
        return record, None

    if existing and existing.get("relevant"):
        return existing, None  # idempotent: re-marking is not an error

    history_entry = {
        "relevant": True,
        "by": user["name"],
        "role": user.get("role"),
        "reason": (reason or "").strip() or None,
        "at": _now(),
    }

    if existing:
        db.case_transaction_relevance.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "relevant": True,
                    "reason": (reason or "").strip() or existing.get("reason"),
                    "marked_by": user["id"],
                    "marked_by_name": user["name"],
                    "marked_at": _now(),
                    "cleared_by": None,
                    "cleared_by_name": None,
                    "cleared_at": None,
                },
                "$push": {"history": history_entry},
            },
        )
    else:
        db.case_transaction_relevance.insert_one({
            "id": f"REL-{uuid.uuid4().hex[:8].upper()}",
            "case_id": case["id"],
            "transaction_id": transaction_id,
            "entity_id": txn.get("entity_id"),
            "amount": txn.get("amount"),
            "bank_id": txn.get("bank_id"),
            "transaction_timestamp": txn.get("timestamp"),
            "relevant": True,
            "reason": (reason or "").strip() or None,
            "marked_by": user["id"],
            "marked_by_name": user["name"],
            "marked_at": _now(),
            "cleared_by": None,
            "cleared_by_name": None,
            "cleared_at": None,
            "history": [history_entry],
        })

    record = db.case_transaction_relevance.find_one(
        {"case_id": case["id"], "transaction_id": transaction_id})
    record.pop("_id", None)
    return record, None


def list_relevance(db, case_id, relevant_only=True):
    q = {"case_id": case_id}
    if relevant_only:
        q["relevant"] = True
    records = list(db.case_transaction_relevance.find(q).sort("marked_at", -1))
    for record in records:
        record.pop("_id", None)
    return records


def relevance_map(db, case_id):
    """`{transaction_id: record}` for the case, so a table can flag rows cheaply."""
    return {r["transaction_id"]: r for r in list_relevance(db, case_id, relevant_only=False)}


def marked_count(db, case_id):
    return db.case_transaction_relevance.count_documents(
        {"case_id": case_id, "relevant": True})
