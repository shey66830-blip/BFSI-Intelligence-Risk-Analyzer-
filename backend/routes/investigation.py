"""
Context Guard — Investigation Working Record Routes

    GET    /api/cases/<case_id>/notes                  working notes on a case
    POST   /api/cases/<case_id>/notes                  add an observation / question / next step
    POST   /api/notes/<note_id>/resolve                close a question or next step
    GET    /api/cases/<case_id>/relevant-transactions  what the analyst has marked
    POST   /api/cases/<case_id>/relevance              mark or clear a transaction

Every endpoint here is scoped: the case must be visible to the caller, and the
permission is checked on the server. Marking relevance annotates a transaction; it
never writes to the transaction record itself.
"""

from flask import Blueprint, jsonify, request

from config import get_db
from middleware import current_user, load_case, login_required
from services import audit, notes as note_service, updates

investigation_bp = Blueprint("investigation", __name__)


def _case_or_error(case_id, permission):
    """Scope + permission check that returns a ready-to-send error tuple."""
    case, error = load_case(case_id, permission=permission)
    if error:
        return None, error
    return case, None


@investigation_bp.route("/api/cases/<case_id>/notes", methods=["GET"])
@login_required
def get_notes(case_id):
    db = get_db()
    case, error = _case_or_error(case_id, "cases:investigate")
    if error:
        return jsonify(error[0]), error[1]

    kind = request.args.get("kind")
    include_resolved = request.args.get("include_resolved", "true").lower() != "false"
    entries = note_service.list_notes(db, case_id, kind=kind, include_resolved=include_resolved)

    audit.record(db, current_user(), "view", target=case_id,
                 case_id=case_id, resource_type="case_notes", resource_id=case_id,
                 detail=f"Viewed {len(entries)} investigation note(s)")

    return jsonify({
        "case_id": case_id,
        "notes": entries,
        "kinds": [
            {"key": key, "label": value["label"], "description": value["description"]}
            for key, value in note_service.NOTE_KINDS.items()
        ],
        "relevance_reasons": note_service.RELEVANCE_REASONS,
        "counts": note_service.note_counts(db, case_id),
    })


@investigation_bp.route("/api/cases/<case_id>/notes", methods=["POST"])
@login_required
def add_note(case_id):
    db = get_db()
    user = current_user()
    case, error = _case_or_error(case_id, "cases:investigate")
    if error:
        return jsonify(error[0]), error[1]

    note, problem = note_service.add_note(db, case, user, request.json or {})
    if problem:
        return jsonify({"error": problem}), 400

    # A note is an investigation update in its own right: compliance has to see the
    # analyst's open questions without opening every case.
    updates.post(
        db, case, user,
        "compliance_note" if note["kind"] == "compliance_note" else "finding",
        title=f"{note['kind_label']} recorded on {case.get('title') or case_id}",
        description=note["body"][:280],
        metadata={"note_id": note["id"], "kind": note["kind"]},
    )

    audit.record(db, user, "action", target=case_id, case_id=case_id,
                 resource_type="case_note", resource_id=note["id"],
                 detail=f"Recorded a {note['kind_label'].lower()}")

    return jsonify({"note": note, "counts": note_service.note_counts(db, case_id)}), 201


@investigation_bp.route("/api/notes/<note_id>/resolve", methods=["POST"])
@login_required
def resolve_note(note_id):
    db = get_db()
    user = current_user()
    note = note_service.get_note(db, note_id)
    if not note:
        return jsonify({"error": "Note not found"}), 404

    case, error = _case_or_error(note["case_id"], "cases:investigate")
    if error:
        return jsonify(error[0]), error[1]

    # Only the author or a reviewer closes a note; an unrelated analyst cannot tidy
    # away someone else's open question.
    if note["author_id"] != user["id"] and user.get("role") == "analyst":
        audit.record(db, user, "access_denied", target=case["id"], case_id=case["id"],
                     detail="Attempted to resolve another analyst's note",
                     result="denied", reason="note belongs to another analyst")
        return jsonify({"error": "This note belongs to another analyst."}), 403

    updated = note_service.resolve_note(db, note, user, (request.json or {}).get("resolution"))
    audit.record(db, user, "action", target=case["id"], case_id=case["id"],
                 resource_type="case_note", resource_id=note_id,
                 detail=f"Resolved a {note.get('kind_label', 'note').lower()}")
    return jsonify({"note": updated, "counts": note_service.note_counts(db, case["id"])})


@investigation_bp.route("/api/cases/<case_id>/relevant-transactions", methods=["GET"])
@login_required
def get_relevance(case_id):
    db = get_db()
    case, error = _case_or_error(case_id, "cases:investigate")
    if error:
        return jsonify(error[0]), error[1]

    records = note_service.list_relevance(db, case_id)
    audit.record(db, current_user(), "view", target=case_id, case_id=case_id,
                 resource_type="case_relevance", resource_id=case_id,
                 detail=f"Viewed {len(records)} marked transaction(s)")

    return jsonify({
        "case_id": case_id,
        "relevant_transactions": records,
        "all": note_service.list_relevance(db, case_id, relevant_only=False),
        "reasons": note_service.RELEVANCE_REASONS,
        "marked_count": len(records),
    })


@investigation_bp.route("/api/cases/<case_id>/relevance", methods=["POST"])
@login_required
def set_relevance(case_id):
    """Mark or clear a transaction's relevance. The financial record is untouched."""
    db = get_db()
    user = current_user()
    case, error = _case_or_error(case_id, "cases:investigate")
    if error:
        return jsonify(error[0]), error[1]

    payload = request.json or {}
    transaction_id = (payload.get("transaction_id") or "").strip()
    if not transaction_id:
        return jsonify({"error": "transaction_id is required"}), 400

    relevant = payload.get("relevant", True)
    if isinstance(relevant, str):
        relevant = relevant.lower() not in ("false", "0", "no", "")

    record, problem = note_service.set_relevance(
        db, case, user, transaction_id, relevant, payload.get("reason"))
    if problem:
        return jsonify({"error": problem}), 400

    audit.record(
        db, user, "action", target=case_id, case_id=case_id,
        resource_type="transaction", resource_id=transaction_id,
        detail=(f"Marked {transaction_id} as relevant"
                + (f" — {record.get('reason')}" if record.get("reason") else "")
                if relevant else f"Cleared relevance on {transaction_id}"),
        metadata={"transaction_id": transaction_id, "relevant": bool(relevant)},
    )

    # Only a new mark is worth telling compliance about; clearing one is housekeeping.
    if relevant:
        updates.post(
            db, case, user, "transaction_identified",
            title=f"Transaction marked relevant on {case.get('title') or case_id}",
            description=(f"{transaction_id} (₹{record.get('amount') or 0:,.0f}) — "
                         f"{record.get('reason') or 'no reason given'}"),
            metadata={"transaction_id": transaction_id},
        )

    return jsonify({
        "relevance": record,
        "marked_count": note_service.marked_count(db, case_id),
    })
