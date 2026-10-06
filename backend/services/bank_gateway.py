"""
Context Guard — The Gateway to a Bank's Consent Desk

A bank is not a local function call. A request for its records leaves the platform, and
the answer comes back later — or does not come back at all. This module is that channel.

It does three things the caller cannot do for itself:

  * holds a request between submission and answer, with the response deadline attached
    to it, instead of pretending the bank replied the instant it was asked;
  * models the transport failing, which is a different thing from the bank refusing —
    a failure is retried inside the window, a refusal is final;
  * enforces the one deadline the platform controls on its own side: when the window
    closes with no answer, the request lapses and nothing is released.

The decision itself is the bank's, not this module's (services/bank_review.py). This
module only carries it, and records every step of the carrying in the audit trail.
"""

import random
from datetime import datetime, timedelta

from services import audit, bank_review, updates
from services.settings import get_settings


def _now():
    return datetime.utcnow()


def _iso(dt):
    return dt.isoformat()


def _parse(value):
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def config(db):
    """The channel's behaviour, as the organisation has configured it."""
    settings = get_settings(db)
    return {
        "latency_seconds": int(settings.get("bank_response_seconds") or 0),
        "deadline_hours": int(settings.get("bank_response_deadline_hours") or 48),
        "failure_rate": float(settings.get("bank_failure_rate") or 0.0),
    }


def _transient_failure(rate):
    """Whether this submission fails in transit. Zero by default, so runs are clean."""
    return rate > 0 and random.random() < rate


def submit(db, case, request_doc):
    """Hand a request to the bank. Returns what happened on this attempt.

    The result is one of:

        settled  — the bank answered, and the decision is in `decision`
        awaiting — the request is held until `respond_at`, inside the response deadline
        failed   — the transport failed; the request is held for a retry inside the window
    """
    channel = config(db)
    now = _now()
    deadline = _iso(now + timedelta(hours=channel["deadline_hours"]))
    attempts = int(request_doc.get("bank_attempts") or 0) + 1
    reviewer = bank_review.reviewer_for(case)

    if _transient_failure(channel["failure_rate"]):
        error = ("The bank's consent desk did not accept the submission "
                 "(the connection was reset).")
        db.access_requests.update_one({"id": request_doc["id"]}, {"$set": {
            "status": "awaiting_bank", "bank_attempts": attempts, "respond_at": None,
            "response_deadline": deadline, "bank_error": error,
            "updated_at": _iso(now)}})
        audit.record(db, None, "bank_gateway_failed", target=request_doc["id"],
                     case_id=request_doc["case_id"], resource_type="access_request",
                     resource_id=request_doc["id"], result="failure", system=True,
                     detail=(f"Submission of {request_doc['id']} to {reviewer['bank_name']} "
                             f"failed in transit on attempt {attempts}; held for retry inside "
                             f"the {channel['deadline_hours']}h window. {error}"),
                     metadata={"attempt": attempts, "response_deadline": deadline})
        return {"state": "failed", "decision": None, "attempts": attempts,
                "response_deadline": deadline, "error": error}

    if channel["latency_seconds"] <= 0:
        decision = bank_review.review(db, case, request_doc)
        return {"state": "settled", "decision": decision, "attempts": attempts,
                "response_deadline": deadline}

    respond_at = _iso(now + timedelta(seconds=channel["latency_seconds"]))
    db.access_requests.update_one({"id": request_doc["id"]}, {"$set": {
        "status": "awaiting_bank", "bank_attempts": attempts, "respond_at": respond_at,
        "response_deadline": deadline, "bank_error": None, "updated_at": _iso(now)}})
    audit.record(db, None, "bank_gateway_awaiting", target=request_doc["id"],
                 case_id=request_doc["case_id"], resource_type="access_request",
                 resource_id=request_doc["id"], system=True,
                 detail=(f"{request_doc['id']} sent to {reviewer['bank_name']}; an answer is "
                         f"expected by {respond_at[:19]}Z and the response deadline is "
                         f"{deadline[:19]}Z."),
                 metadata={"attempt": attempts, "respond_at": respond_at,
                           "response_deadline": deadline})
    return {"state": "awaiting", "decision": None, "attempts": attempts,
            "respond_at": respond_at, "response_deadline": deadline}


def settle(db, case, request_doc, decision, bank_identity=None):
    """Apply an answer that has arrived. Returns (request, authorisation).

    The answer can approve the whole request, approve part of it, refuse it, or ask for
    clarification. Whatever it is, the bank's words and the platform's response to them
    are recorded, and the requester is told.
    """
    from services import access as access_service

    bank_identity = bank_identity or bank_review.reviewer_for(case)
    request_doc, authorization = access_service.settle_bank_request(
        db, request_doc, decision, bank_identity)

    audit.record(db, bank_identity, "bank_access_decision", target=request_doc["id"],
                 case_id=request_doc["case_id"], resource_type="access_request",
                 resource_id=request_doc["id"],
                 detail=(f"{decision['bank_name']} decided {request_doc['id']} — "
                         f"{decision['outcome']}: {decision['statement']}"),
                 metadata={"reasons": decision.get("reasons"),
                           "policy_refs": decision.get("policy_refs"),
                           "approved_keys": decision.get("approved_keys"),
                           "refused_keys": decision.get("refused_keys")})
    action = {"approved": "access_request_approved",
              "partially_approved": "access_request_approved",
              "rejected": "access_request_rejected",
              "clarification_requested": "access_request_clarification"}[decision["outcome"]]
    audit.record(db, bank_identity, action, target=request_doc["id"],
                 case_id=request_doc["case_id"], resource_type="access_request",
                 resource_id=request_doc["id"],
                 detail=(f"Bank decision on {request_doc['id']} for "
                         f"{request_doc['requested_by_name']}"
                         + (f" — releasing until {authorization['expires_at'][:16]}Z"
                            if authorization else "")))
    if authorization:
        audit.record(db, bank_identity, "access_capability_granted",
                     target=authorization["id"], case_id=request_doc["case_id"],
                     resource_type="access_authorization",
                     resource_id=authorization["id"],
                     detail=(f"Released {', '.join(authorization['unlock_labels'])} to "
                             f"{request_doc['requested_by_name']} until "
                             f"{authorization['expires_at'][:16]}Z"))
        updates.notify_user(
            db, request_doc["requested_by"], "access_approved",
            f"Bank approved — {request_doc['id']}",
            f"{', '.join(authorization['scope_labels'])} released by "
            f"{decision['bank_name']} until {authorization['expires_at'][:16]}Z.",
            case_id=request_doc["case_id"], link=f"restricted:{request_doc['case_id']}",
            severity="high",
        )
    else:
        updates.notify_user(
            db, request_doc["requested_by"], "access_decision",
            f"Bank decision — {request_doc['id']}",
            decision["statement"], case_id=request_doc["case_id"],
            link=f"access:{request_doc['id']}",
        )
    return request_doc, authorization


def lapse(db, case, request_doc, deadline):
    """Close a request the bank never answered inside its window."""
    reviewer = bank_review.reviewer_for(case)
    hours = config(db)["deadline_hours"]
    statement = (f"No response within the {hours}-hour window. {reviewer['bank_name']} did not "
                 f"return a decision on this request by {str(deadline)[:16]}Z, so the request "
                 f"has lapsed. Nothing has been released; it can be resubmitted.")
    now = _iso(_now())
    db.access_requests.update_one({"id": request_doc["id"]}, {
        "$set": {"status": "expired", "respond_at": None, "bank_error": None,
                 "deadline_missed_at": now, "updated_at": now}})
    from services import access as access_service
    access_service.record_statement(
        db, reviewer, request_doc, "bank_statement", statement,
        {"outcome": "expired", "response_deadline": request_doc.get("response_deadline")})
    audit.record(db, reviewer, "bank_response_deadline_expired", target=request_doc["id"],
                 case_id=request_doc["case_id"], resource_type="access_request",
                 resource_id=request_doc["id"], result="expired", detail=statement)
    updates.notify_user(
        db, request_doc["requested_by"], "access_decision",
        f"Bank did not respond — {request_doc['id']}", statement,
        case_id=request_doc["case_id"], link=f"access:{request_doc['id']}",
    )
    return statement


def sweep(db, case=None):
    """Deliver answers that have come due, and lapse requests past their deadline.

    Called lazily on reads (through `access.expire_stale`) rather than from a background
    worker, so a request settles the next time anybody looks — the same laziness the rest
    of the access model already uses for expiry.
    """
    settled = 0
    expired = 0
    now = _now()
    for request_doc in list(db.access_requests.find({"status": "awaiting_bank"})):
        case_doc = case or db.cases.find_one({"id": request_doc["case_id"]}) or {
            "id": request_doc["case_id"], "title": request_doc.get("case_title"),
            "bank_ids": [], "entity_ids": [],
        }
        deadline = _parse(request_doc.get("response_deadline"))
        if deadline and deadline <= now:
            lapse(db, case_doc, request_doc, deadline)
            expired += 1
            continue
        respond_at = _parse(request_doc.get("respond_at"))
        if not respond_at or respond_at > now:
            continue
        db.access_requests.update_one({"id": request_doc["id"]},
                                      {"$inc": {"bank_attempts": 1}})
        decision = bank_review.review(db, case_doc, request_doc)
        settle(db, case_doc, request_doc, decision)
        settled += 1
    return settled, expired
