"""
Context Guard — Analyst Report Routes

    GET    /api/analyst/reports                     my reports
    POST   /api/analyst/reports/<id>/submit         submit a draft to compliance
    POST   /api/analyst/reports/<id>/amend          start the next version
    POST   /api/analyst/reports/<id>/clarification  compliance sends it back
    POST   /api/analyst/reports/<id>/review         compliance records a review
    GET    /api/compliance/reports                  submitted reports awaiting review

    GET    /api/cases/<case_id>/analyst-reports     every version on a case
    POST   /api/cases/<case_id>/analyst-report      create a draft (optionally prefilled)
    GET    /api/reports/<report_id>                 one version
    PATCH  /api/reports/<report_id>                 edit a draft
"""

from flask import Blueprint, jsonify, request

from config import get_db
from middleware import can, current_user, load_case, login_required, visible_case_ids
from services import audit, reports as report_service, updates, workflow

reports_bp = Blueprint("reports", __name__)


def _serialize(report):
    report = dict(report)
    report.pop("_id", None)
    report["finding_groups"] = report_service.finding_groups(report)
    return report


def _move_case(db, case, target, user):
    """Advance the case if the workflow allows it, without failing the request.

    A refusal never blocks the action that triggered it — the report is still filed —
    but it is recorded, so why a case stayed put is answerable afterwards.
    """
    allowed, reason = workflow.can_transition(case.get("status"), target, user.get("role"))
    if not allowed:
        audit.record(db, user, "status_change_refused", target=case["id"], case_id=case["id"],
                     resource_type="case", resource_id=case["id"],
                     detail=f"Kept {workflow.label_for(case.get('status'))}: {reason}",
                     result="denied", reason=reason)
        return None
    db.cases.update_one({"id": case["id"]}, {"$set": {"status": target}})
    updates.post(db, case, user, "status_change",
                 title=f"Status moved to {workflow.label_for(target)}",
                 description=f"Set automatically when the analyst report was submitted.",
                 metadata={"from": case.get("status"), "to": target})
    return target


@reports_bp.route("/api/analyst/reports", methods=["GET"])
@login_required
def my_reports():
    db = get_db()
    user = current_user()
    case_ids = visible_case_ids(db, user)
    report_list = report_service.list_reports(
        db, case_ids=case_ids, analyst_id=user["id"] if user["role"] == "analyst" else None,
    )
    return jsonify({
        "reports": [_serialize(r) for r in report_list],
        "can_submit": can("reports:submit"),
    })


@reports_bp.route("/api/compliance/reports", methods=["GET"])
@login_required
def compliance_reports():
    """Reports that have been handed to compliance for review."""
    db = get_db()
    user = current_user()
    if not can("reports:review"):
        audit.record(db, user, "access_denied", target="compliance_reports",
                     detail="Missing permission reports:review", resource_type="analyst_report",
                     result="denied", reason="requires reports:review")
        return jsonify({"error": "Your role cannot review analyst reports.",
                        "code": "forbidden", "required_permission": "reports:review"}), 403

    statuses = request.args.get("status")
    statuses = statuses.split(",") if statuses else ["submitted", "clarification_requested"]
    case_ids = visible_case_ids(db, user)
    report_list = report_service.list_reports(db, case_ids=case_ids, statuses=statuses)

    cases = {c["id"]: c for c in db.cases.find({}, {"id": 1, "title": 1, "status": 1, "score": 1})}
    for report in report_list:
        case = cases.get(report.get("case_id"), {})
        report["case_status"] = case.get("status")
        report["case_score"] = case.get("score")

    return jsonify({
        "reports": [_serialize(r) for r in report_list],
        "counts": {
            status: sum(1 for r in report_list if r.get("status") == status)
            for status in set(r.get("status") for r in report_list)
        },
    })


@reports_bp.route("/api/cases/<case_id>/analyst-reports", methods=["GET"])
@login_required
def case_reports(case_id):
    db = get_db()
    _, error = load_case(case_id)
    if error:
        return jsonify(error[0]), error[1]

    versions = list(db.analyst_reports.find({"case_id": case_id}).sort("version", -1))
    return jsonify({
        "case_id": case_id,
        "versions": [_serialize(v) for v in versions],
        "latest": _serialize(versions[0]) if versions else None,
    })


@reports_bp.route("/api/cases/<case_id>/analyst-report", methods=["POST"])
@login_required
def create_report(case_id):
    db = get_db()
    user = current_user()
    case, error = load_case(case_id, permission="reports:create")
    if error:
        return jsonify(error[0]), error[1]

    draft = report_service.latest_for_case(db, case_id)
    if draft and draft.get("status") == "draft" and draft.get("analyst_id") == user["id"]:
        return jsonify({"report": _serialize(draft), "reused": True})

    payload = request.json or {}
    if payload.get("build_from_case", True):
        built = report_service.build_draft_from_case(db, case, user)
        payload = {**payload, **built}

    report = report_service.create_draft(db, case, user, payload)
    audit.record(db, user, "report_created", target=report["id"], case_id=case_id,
                 resource_type="analyst_report", resource_id=report["id"],
                 detail=f"Drafted version {report['version']} from case evidence")
    return jsonify({"report": _serialize(report)}), 201


@reports_bp.route("/api/reports/<report_id>", methods=["GET"])
@login_required
def read_report(report_id):
    db = get_db()
    report = report_service.get_report(db, report_id)
    if not report:
        return jsonify({"error": "Report not found"}), 404
    case, error = load_case(report["case_id"])
    if error:
        return jsonify(error[0]), error[1]

    audit.record(db, current_user(), "view", target=report_id, case_id=report["case_id"],
                 resource_type="analyst_report", resource_id=report_id,
                 detail=f"Viewed analyst report version {report.get('version')}")
    return jsonify({"report": _serialize(report)})


@reports_bp.route("/api/reports/<report_id>", methods=["PATCH"])
@login_required
def edit_report(report_id):
    db = get_db()
    user = current_user()
    report = report_service.get_report(db, report_id)
    if not report:
        return jsonify({"error": "Report not found"}), 404
    case, error = load_case(report["case_id"], permission="reports:create")
    if error:
        return jsonify(error[0]), error[1]

    updated, message = report_service.update_draft(db, report, user, request.json or {})
    if message:
        return jsonify({"error": message}), 409
    return jsonify({"report": _serialize(updated)})


@reports_bp.route("/api/analyst/reports/<report_id>/submit", methods=["POST"])
@login_required
def submit_report(report_id):
    db = get_db()
    user = current_user()
    report = report_service.get_report(db, report_id)
    if not report:
        return jsonify({"error": "Report not found"}), 404
    case, error = load_case(report["case_id"], permission="reports:submit")
    if error:
        return jsonify(error[0]), error[1]

    submitted, message = report_service.submit(db, report, user)
    if message:
        return jsonify({"error": message}), 409

    audit.record(db, user, "report_submitted", target=report_id, case_id=case["id"],
                 resource_type="analyst_report", resource_id=report_id,
                 detail=f"Submitted version {submitted['version']} to compliance")
    updates.post(db, case, user, "analyst_report",
                 title=f"Analyst report v{submitted['version']} submitted",
                 description=(submitted.get("summary") or
                              f"{user['name']} submitted an investigation report for review."),
                 metadata={"report_id": report_id, "version": submitted["version"]})
    _move_case(db, case, "analyst_report_submitted", user)

    return jsonify({"report": _serialize(submitted)})


@reports_bp.route("/api/analyst/reports/<report_id>/amend", methods=["POST"])
@login_required
def amend_report(report_id):
    """Start the next version. The submitted version is never overwritten."""
    db = get_db()
    user = current_user()
    prior = report_service.get_report(db, report_id)
    if not prior:
        return jsonify({"error": "Report not found"}), 404
    case, error = load_case(prior["case_id"], permission="reports:create")
    if error:
        return jsonify(error[0]), error[1]
    if user["role"] == "analyst" and prior.get("analyst_id") != user["id"]:
        return jsonify({"error": "Only the drafting analyst can amend this report"}), 403

    payload = request.json or {}
    reason = (payload.get("reason") or "").strip()
    if not reason:
        return jsonify({"error": "An amendment needs a reason, so the change is auditable"}), 400

    draft = report_service.create_draft(
        db, case, user,
        {**payload, "sections": prior.get("sections"), "findings": prior.get("findings"),
         "title": prior.get("title"), "summary": prior.get("summary")},
        prior=prior, reason=reason,
    )
    audit.record(db, user, "report_amended", target=draft["id"], case_id=case["id"],
                 resource_type="analyst_report", resource_id=draft["id"],
                 detail=f"Opened version {draft['version']} amending v{prior['version']}: {reason}")
    updates.post(db, case, user, "analyst_report_revised",
                 title=f"Report amended — v{draft['version']} drafted",
                 description=reason, metadata={"report_id": draft["id"], "supersedes": prior["id"]})
    return jsonify({"report": _serialize(draft)}), 201


@reports_bp.route("/api/analyst/reports/<report_id>/clarification", methods=["POST"])
@login_required
def clarification(report_id):
    db = get_db()
    user = current_user()
    report = report_service.get_report(db, report_id)
    if not report:
        return jsonify({"error": "Report not found"}), 404
    case, error = load_case(report["case_id"], permission="reports:clarify")
    if error:
        return jsonify(error[0]), error[1]

    note = (request.json or {}).get("note")
    updated, message = report_service.request_clarification(db, report, user, note)
    if message:
        return jsonify({"error": message}), 400

    audit.record(db, user, "compliance_review", target=report_id, case_id=case["id"],
                 resource_type="analyst_report", resource_id=report_id,
                 detail=f"Requested clarification on v{report['version']}")
    updates.post(db, case, user, "clarification",
                 title="Clarification requested on the analyst report",
                 description=note, metadata={"report_id": report_id})
    return jsonify({"report": _serialize(updated)})


@reports_bp.route("/api/analyst/reports/<report_id>/review", methods=["POST"])
@login_required
def review_report(report_id):
    db = get_db()
    user = current_user()
    report = report_service.get_report(db, report_id)
    if not report:
        return jsonify({"error": "Report not found"}), 404
    case, error = load_case(report["case_id"], permission="reports:review")
    if error:
        return jsonify(error[0]), error[1]

    payload = request.json or {}
    outcome = payload.get("outcome") or "accepted"
    if outcome not in ("accepted", "returned"):
        return jsonify({"error": "Outcome must be 'accepted' or 'returned'"}), 400
    if outcome == "returned" and not (payload.get("note") or "").strip():
        return jsonify({"error": "Returning a report requires a note explaining why"}), 400

    updated, message = report_service.record_review(db, report, user, outcome, payload.get("note"))
    if message:
        return jsonify({"error": message}), 409

    audit.record(db, user, "compliance_review", target=report_id, case_id=case["id"],
                 resource_type="analyst_report", resource_id=report_id,
                 detail=f"Review outcome: {outcome}")
    if outcome == "accepted":
        _move_case(db, case, "compliance_review", user)
    updates.post(db, case, user, "compliance_note",
                 title=f"Compliance review — {outcome}",
                 description=payload.get("note") or f"Report v{report['version']} {outcome}.",
                 metadata={"report_id": report_id, "outcome": outcome})
    return jsonify({"report": _serialize(updated)})
