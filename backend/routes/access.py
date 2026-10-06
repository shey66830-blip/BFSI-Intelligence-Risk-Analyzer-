"""
Context Guard — Restricted Information Routes

    POST /api/access-requests                     request restricted subject information
    GET  /api/access-requests                     admin queue, or my own requests
    GET  /api/access-requests/<id>                one request
    POST /api/access-requests/<id>/approve|reject|clarification
    GET  /api/access-authorizations               active and historical authorisations
    POST /api/access-authorizations/<id>/revoke   revoke early

    GET  /api/restricted/<case_id>                released subject information, or the lock
    GET  /api/restricted/<case_id>/matrix         which categories exist (no values)
    POST /api/cases/<case_id>/subject-information administrator adds a record
"""

from flask import Blueprint, g, jsonify, request

from config import MAX_ACCESS_DURATION_DAYS, get_db
from middleware import can, current_user, load_case, login_required, visible_case_ids
from services import access as access_service, audit, bank_gateway, bank_review, paging, updates

access_bp = Blueprint("access", __name__)


def _gate(db, user, case_id, category=None):
    """Returns (authorization, error_response). Administrator is not exempt."""
    allowed, authorization, reason = access_service.restricted_access(db, user, case_id, category)
    if allowed:
        return authorization, None
    if can("access:request") or user.get("role") == "admin":
        # Someone who could ask for access gets an explanation, not a bare refusal.
        return None, None
    audit.record(db, user, "restricted_denied", target=case_id, case_id=case_id,
                 resource_type="restricted_subject_information", result="denied",
                 reason=reason)
    return None, ({"error": reason, "code": "restricted", "locked": True}, 403)


@access_bp.route("/api/access-requests", methods=["GET"])
@login_required
def list_requests():
    db = get_db()
    user = current_user()
    access_service.expire_stale(db)

    status = request.args.get("status")
    statuses = status.split(",") if status and status != "all" else None

    if can("access:approve"):
        all_requests = access_service.list_requests(db, statuses=statuses)
    else:
        all_requests = access_service.list_requests(db, requester_id=user["id"], statuses=statuses)

    # The counts describe the whole queue; the page describes what was asked for. A
    # count that only covered the visible page would misreport the workload.
    counts = {
        state: sum(1 for r in all_requests if r.get("status") == state)
        for state in ("pending", "awaiting_bank", "approved", "partially_approved",
                      "rejected", "clarification_requested", "expired")
    }
    limit, offset = paging.window(request.args)
    requests_list, total = paging.slice_page(all_requests, limit, offset)

    scope = "all" if can("access:approve") else "own"
    return jsonify({
        "requests": requests_list,
        "scope": scope,
        "can_decide": can("access:approve"),
        "can_request": can("access:request"),
        "pagination": paging.envelope(requests_list, total, limit, offset),
        "counts": counts,
        "max_duration_days": MAX_ACCESS_DURATION_DAYS,
        "duration_options": access_service.DURATION_OPTIONS,
        "categories": access_service.CATEGORIES,
    })


@access_bp.route("/api/access-requests", methods=["POST"])
@login_required
def create_request():
    db = get_db()
    user = current_user()
    payload = request.json or {}
    case_id = payload.get("case_id")
    if not case_id:
        return jsonify({"error": "case_id is required"}), 400

    case, error = load_case(case_id)
    if error:
        return jsonify(error[0]), error[1]
    if not can("access:request"):
        return jsonify({"error": "Your role cannot request restricted information. An "
                                "administrator approves these requests but cannot raise "
                                "one — a compliance officer submits them.",
                        "code": "forbidden", "required_permission": "access:request"}), 403

    # Two doors lead here. A request for a locked capability or a bank-held record names
    # the items; a request for restricted subject information names categories. They are
    # decided by different parties, so they are raised as different requests.
    if payload.get("resource_keys"):
        request_doc, message = access_service.create_resource_request(db, case, user, payload)
    else:
        request_doc, message = access_service.create_request(db, case, user, payload)
    if message:
        return jsonify({"error": message}), 400

    items = request_doc.get("resource_labels") or request_doc.get("category_labels") or []
    audit.record(db, user, "access_request_created", target=request_doc["id"], case_id=case_id,
                 resource_type="access_request", resource_id=request_doc["id"],
                 detail=f"Requested {', '.join(items)} for "
                        f"{request_doc['duration_days']} day(s) — decided by "
                        f"{request_doc.get('decider') or 'an organisation administrator'}: "
                        f"{request_doc.get('statement') or request_doc.get('reason')}")
    updates.post(db, case, user, "access_request",
                 title=f"Access requested — {request_doc['id']}",
                 description=f"{user['name']} requested {', '.join(items)} "
                             f"for {request_doc['duration_days']} day(s).",
                 metadata={"request_id": request_doc["id"],
                           "categories": request_doc.get("categories"),
                           "resources": request_doc.get("resource_keys")})

    # Bank-held records are not ours to grant: the request leaves the platform and the
    # bank answers in its own words — later, or not at all. The gateway carries it, sets
    # the response deadline and records every step of the carrying.
    bank_decision = None
    authorization = None
    bank_state = "not_applicable"
    if request_doc.get("track") == "bank":
        outcome = bank_gateway.submit(db, case, request_doc)
        bank_state = outcome["state"]
        if outcome["state"] == "settled":
            request_doc, authorization = bank_gateway.settle(
                db, case, request_doc, outcome["decision"])
            bank_decision = outcome["decision"]
        else:
            # Held for the bank. The request itself carries the window and the deadline.
            request_doc = access_service.get_request(db, request_doc["id"])

    return jsonify({"request": request_doc, "authorization": authorization,
                    "bank_decision": bank_decision, "bank_state": bank_state}), 201


@access_bp.route("/api/access-requests/<request_id>", methods=["GET"])
@login_required
def read_request(request_id):
    db = get_db()
    user = current_user()
    # Polling a request is also the moment a due bank answer is delivered.
    access_service.expire_stale(db)
    request_doc = access_service.get_request(db, request_id)
    if not request_doc:
        return jsonify({"error": "Request not found"}), 404

    if not can("access:approve") and request_doc["requested_by"] != user["id"]:
        audit.record(db, user, "access_denied", target=request_id,
                     case_id=request_doc.get("case_id"), resource_type="access_request",
                     resource_id=request_id, result="denied",
                     reason="request belongs to another user")
        return jsonify({"error": "This request belongs to another user", "code": "forbidden"}), 403

    authorization = None
    if request_doc.get("authorization_id"):
        authorization = db.access_authorizations.find_one({"id": request_doc["authorization_id"]})
        if authorization:
            authorization.pop("_id", None)
            authorization["is_active"] = (
                not authorization.get("revoked_at")
                and str(authorization.get("expires_at")) > access_service._iso(access_service._now())
            )

    return jsonify({"request": request_doc, "authorization": authorization})


def _decide(request_id, status):
    db = get_db()
    user = current_user()

    if not can("access:approve"):
        audit.record(db, user, "access_denied", target=request_id, resource_type="access_request",
                     resource_id=request_id, result="denied", reason="requires access:approve")
        return jsonify({"error": "Only an organisation administrator can decide access requests",
                        "code": "forbidden", "required_permission": "access:approve"}), 403

    payload = request.json or {}
    request_doc, authorization, message = access_service.request_for_update(
        db, request_id, user, status,
        reason=payload.get("reason"), note=payload.get("note"),
        duration_days=payload.get("duration_days"), scope=payload.get("scope"),
    )
    if message:
        # A self-approval attempt is a 403, everything else is a 400.
        code = 403 if "your own access request" in message else 400
        audit.record(db, user, "access_denied", target=request_id, resource_type="access_request",
                     resource_id=request_id, result="denied", reason=message)
        return jsonify({"error": message, "code": "forbidden" if code == 403 else "invalid"}), code

    # Whatever the decider said is recorded in full, whether or not any screen shows it.
    note_text = (payload.get("note") or payload.get("reason") or "").strip()
    if note_text:
        access_service.record_statement(db, user, request_doc, "administrator_statement",
                                        note_text, {"outcome": request_doc.get("status")})

    case = db.cases.find_one({"id": request_doc["case_id"]}) or {"id": request_doc["case_id"],
                                                                "title": request_doc.get("case_title")}
    action = {"approved": "access_request_approved", "rejected": "access_request_rejected",
              "clarification_requested": "access_request_clarification"}[status]
    audit.record(db, user, action, target=request_id, case_id=request_doc["case_id"],
                 resource_type="access_request", resource_id=request_id,
                 detail=(f"{action.replace('_', ' ')} for {request_doc['requested_by_name']}"
                         + (f" — scope {', '.join(authorization['scope_labels'])} until "
                            f"{authorization['expires_at'][:16]}Z" if authorization else "")),
                 reason=payload.get("reason") or payload.get("note"))

    updates.post(db, case, user, "access_decision",
                 title=f"Access request {request_doc['id']} — {request_doc['status'].replace('_', ' ')}",
                 description=(payload.get("reason") or payload.get("note")
                              or f"Decided by {user['name']}"),
                 metadata={"request_id": request_id, "status": request_doc["status"]})

    # Tell the requester what happened.
    if authorization:
        updates.notify_user(
            db, request_doc["requested_by"], "access_approved",
            f"Restricted access approved — {request_doc['id']}",
            f"{', '.join(authorization['scope_labels'])} released for case "
            f"{request_doc['case_id']} until {authorization['expires_at'][:16]}Z.",
            case_id=request_doc["case_id"], link=f"restricted:{request_doc['case_id']}",
            severity="high",
        )
    else:
        updates.notify_user(
            db, request_doc["requested_by"], "access_decision",
            f"Access request {request_doc['id']} — {request_doc['status'].replace('_', ' ')}",
            payload.get("reason") or payload.get("note") or "See the request for details.",
            case_id=request_doc["case_id"], link=f"access:{request_id}",
        )

    return jsonify({"request": request_doc, "authorization": authorization})


@access_bp.route("/api/access-requests/<request_id>/approve", methods=["POST"])
@login_required
def approve_request(request_id):
    return _decide(request_id, "approved")


@access_bp.route("/api/access-requests/<request_id>/reject", methods=["POST"])
@login_required
def reject_request(request_id):
    return _decide(request_id, "rejected")


@access_bp.route("/api/access-requests/<request_id>/clarification", methods=["POST"])
@login_required
def clarify_request(request_id):
    return _decide(request_id, "clarification_requested")


@access_bp.route("/api/access-authorizations", methods=["GET"])
@login_required
def list_authorizations():
    db = get_db()
    user = current_user()
    access_service.expire_stale(db)

    case_id = request.args.get("case_id")
    if can("access:approve"):
        authorizations = access_service.list_authorizations(db, case_id=case_id)
        scope = "all"
    else:
        authorizations = access_service.list_authorizations(db, case_id=case_id, user_id=user["id"])
        scope = "own"

    for authorization in authorizations:
        authorization["remaining"] = access_service.expiry_label(authorization)
    return jsonify({"authorizations": authorizations, "scope": scope})


@access_bp.route("/api/access-authorizations/<authorization_id>/revoke", methods=["POST"])
@login_required
def revoke_authorization(authorization_id):
    db = get_db()
    user = current_user()
    if not can("access:approve"):
        return jsonify({"error": "Only an organisation administrator can revoke an authorisation",
                        "code": "forbidden"}), 403

    doc, message = access_service.revoke(db, authorization_id, user, (request.json or {}).get("reason"))
    if message:
        return jsonify({"error": message}), 404

    audit.record(db, user, "permission_changed", target=authorization_id,
                 case_id=doc.get("case_id"), resource_type="access_authorization",
                 resource_id=authorization_id,
                 detail=f"Revoked restricted access for {doc.get('granted_to_name')}",
                 reason=(request.json or {}).get("reason"))
    return jsonify({"authorization": doc})


# ── Restricted subject information ───────────────────────────────────────────

@access_bp.route("/api/restricted/<case_id>", methods=["GET"])
@login_required
def restricted_information(case_id):
    """The gated read. Locked unless an active authorisation covers this caller."""
    db = get_db()
    user = current_user()
    case, error = load_case(case_id)
    if error:
        return jsonify(error[0]), error[1]
    access_service.expire_stale(db)

    matrix = access_service.vector(db, case_id)
    authorization, denied = _gate(db, user, case_id)
    if denied:
        return jsonify(denied[0]), denied[1]

    if not authorization:
        # Show the lock, the reason, and where the request stands — never the values.
        pending = db.access_requests.find_one({"case_id": case_id, "requested_by": user["id"],
                                               "status": "pending"})
        expired = access_service.expired_authorization(db, user["id"], case_id)
        audit.record(db, user, "restricted_denied", target=case_id, case_id=case_id,
                     resource_type="restricted_subject_information", result="denied",
                     reason="no active authorisation")
        return jsonify({
            "case_id": case_id,
            "locked": True,
            "state": "pending" if pending else ("expired" if expired else "locked"),
            "reason": (f"Request {pending['id']} is awaiting administrator approval."
                       if pending else
                       (f"Access expired on {str(expired['expires_at'])[:16]}Z. Submit a new request "
                        f"if the information is still required." if expired else
                        "Restricted subject information requires an approved access request.")),
            "matrix": matrix,
            "pending_request": pending,
            "expired_authorization": expired,
            "can_request": can("access:request"),
            "records": [],
        })

    records = access_service.released(db, case_id, user, authorization)
    for record in records:
        audit.record(db, user, "restricted_accessed", target=record["id"], case_id=case_id,
                     resource_type="restricted_subject_information", resource_id=record["id"],
                     detail=f"{record['category']} — {record['title']} "
                            f"(authorised under {authorization['request_id']})")
    audit.record(db, user, "restricted_accessed", target=case_id, case_id=case_id,
                 resource_type="restricted_subject_information",
                 detail=f"Opened restricted subject information ({len(records)} record(s), "
                        f"authorisation {authorization['id']})")

    return jsonify({
        "case_id": case_id,
        "locked": False,
        "state": "authorized",
        "authorization": authorization,
        "remaining": access_service.expiry_label(authorization),
        "matrix": matrix,
        "records": records,
        "notice": access_service.NO_DETERMINATION_NOTICE,
        "can_request": can("access:request"),
    })


@access_bp.route("/api/restricted/<case_id>/matrix", methods=["GET"])
@login_required
def restricted_matrix(case_id):
    """Which categories of restricted information exist — no values, no gate needed."""
    db = get_db()
    user = current_user()
    _, error = load_case(case_id)
    if error:
        return jsonify(error[0]), error[1]
    return jsonify(access_service.vector(db, case_id))


@access_bp.route("/api/cases/<case_id>/subject-information", methods=["POST"])
@login_required
def add_subject_information(case_id):
    """Only an administrator may add to the restricted store; reads stay gated."""
    db = get_db()
    user = current_user()
    _, error = load_case(case_id)
    if error:
        return jsonify(error[0]), error[1]
    if user.get("role") != "admin":
        return jsonify({"error": "Only an organisation administrator can add restricted records",
                        "code": "forbidden"}), 403

    payload = request.json or {}
    if payload.get("category") not in access_service.CATEGORY_KEYS:
        return jsonify({"error": "Unknown category"}), 400

    doc = access_service.add_subject_information(db, case_id, payload)
    audit.record(db, user, "action", target=doc["id"], case_id=case_id,
                 resource_type="restricted_subject_information", resource_id=doc["id"],
                 detail=f"Added {doc['category']} record for subject {doc.get('subject_id')}")
    doc.pop("_id", None)
    return jsonify({"record": doc}), 201


# ── Locked features and information ──────────────────────────────────────────

@access_bp.route("/api/locked-resources", methods=["GET"])
@login_required
def locked_resources():
    """What is locked for this caller on this case, and who is able to release it.

    Bank-held items are served here once a bank has released them, so a grant shows the
    records it covers rather than merely asserting that access exists.
    """
    db = get_db()
    user = current_user()
    case_id = request.args.get("case_id")
    if not case_id:
        return jsonify({"error": "case_id is required"}), 400

    case, error = load_case(case_id)
    if error:
        return jsonify(error[0]), error[1]
    access_service.expire_stale(db)

    items = access_service.catalogue(db, case_id, user)
    released = []
    for item in items:
        if item["state"] != "granted" or item["track"] != "bank":
            continue
        authorization = access_service.active_authorization(db, user["id"], case_id, item["key"])
        if not authorization:
            continue
        for record in bank_review.release(db, case, authorization):
            if record["resource"] != item["key"]:
                continue
            audit.record(db, user, "restricted_accessed", target=case_id, case_id=case_id,
                         resource_type="bank_release", resource_id=record["resource"],
                         detail=f"Opened {record['title']} under {authorization['request_id']}")
            released.append({**record, "authorization_id": authorization["id"],
                             "request_id": authorization["request_id"],
                             "released_by": authorization.get("approved_by_name"),
                             "expires_at": authorization.get("expires_at"),
                             # The record carries its own account of where it came from:
                             # which request, which authorisation, which bank, released
                             # to whom and under what expiry.
                             "provenance": {
                                 "origin": "bank_release",
                                 "origin_label": "released by a bank under an authorisation",
                                 "bank": authorization.get("approved_by_name"),
                                 "decider_type": authorization.get("decider_type"),
                                 "request_id": authorization.get("request_id"),
                                 "authorization_id": authorization["id"],
                                 "released_at": authorization.get("approved_at"),
                                 "released_to": authorization.get("granted_to_name"),
                                 "expires_at": authorization.get("expires_at"),
                                 "case_id": case_id,
                             }})

    unlocks = sorted(getattr(g, "grants", set()) or access_service.active_unlocks(db, user["id"]))
    return jsonify({
        "case_id": case_id,
        "resources": items,
        "released": released,
        "can_request": can("access:request"),
        "can_decide": can("access:approve"),
        "min_statement_words": access_service.MIN_STATEMENT_WORDS,
        "active_unlocks": unlocks,
        "tracks": access_service.TRACK_DECIDER,
    })


@access_bp.route("/api/access-requests/<request_id>/statements", methods=["GET"])
@login_required
def request_statements(request_id):
    """The statements recorded against a request — the requester's, and whoever decided.

    Recorded in full whether or not the interface displays them; visible to the person
    who made the request and to whoever has to decide it.
    """
    db = get_db()
    user = current_user()
    request_doc = access_service.get_request(db, request_id)
    if not request_doc:
        return jsonify({"error": "Request not found"}), 404
    if not can("access:approve") and request_doc["requested_by"] != user["id"]:
        audit.record(db, user, "access_denied", target=request_id,
                     case_id=request_doc.get("case_id"), resource_type="access_request",
                     resource_id=request_id, result="denied",
                     reason="statements belong to another user")
        return jsonify({"error": "This request belongs to another user", "code": "forbidden"}), 403
    return jsonify({"request_id": request_id,
                    "statements": request_doc.get("statements") or []})
