"""
Context Guard — Pipeline Routes

Flask blueprint for the 12-stage investigation pipeline.
"""

from flask import Blueprint, jsonify, request
from datetime import datetime
import uuid

from config import get_db, ANOMALY_THRESHOLD, INVESTIGATION_THRESHOLD
from middleware import can, case_access, current_user, login_required
from models import (
    serialize_doc, create_case, update_case, get_case,
    create_bank_report, get_reports_by_case,
    create_decision, get_decision_by_case,
    get_transactions_by_case, get_all_transactions,
)
from services import audit, evidence
from services import updates as update_service
from services.mock_banks import (
    create_context_request, create_investigation_request,
    get_mock_response, MOCK_BANK_ENDPOINTS,
)
from services.graph_engine import expand_network, resolve_depth
from services.settings import get_settings
from services.users import LIMITED_DECISIONS

pipeline_bp = Blueprint("pipeline", __name__)


def _allowed_decision_options(role):
    """Analysts may close or ask for context; escalation needs compliance."""
    if can("cases:decide"):
        return DECISION_OPTIONS
    return [o for o in DECISION_OPTIONS if o["value"] in LIMITED_DECISIONS]


# ── Pipeline flow definition ─────────────────────────────────────────────────

STAGES = [
    {"key": "transaction", "order": 1, "title": "Transaction occurs",
     "actor": "system", "description": "A new transaction is recorded at its originating bank."},
    {"key": "initial_analysis", "order": 2, "title": "Initial AI analysis",
     "actor": "system", "description": "Each transaction is scored against the account's own baseline and known patterns."},
    {"key": "anomaly_gate", "order": 3, "title": "Meaningful anomaly or pattern?",
     "actor": "system", "description": "Gate: is there enough signal to justify human attention, or is this routine?"},
    {"key": "case_created", "order": 4, "title": "Investigation case created",
     "actor": "system", "description": "An anomaly opens a case — a container for evidence, requests, and decisions."},
    {"key": "banks_identified", "order": 5, "title": "Relevant banks identified",
     "actor": "system", "description": "Banks holding the accounts and counterparties involved are determined from the evidence."},
    {"key": "request_sent", "order": 6, "title": "Investigation request sent",
     "actor": "system", "description": "A structured, consent-scoped request goes to each identified bank."},
    {"key": "bank_analysis", "order": 7, "title": "Simulated banks analyze their own data",
     "actor": "bank", "description": "Each bank searches its own records. No bank sees another bank's raw data."},
    {"key": "reports_returned", "order": 8, "title": "Structured reports returned",
     "actor": "bank", "description": "Banks answer with structured findings only — not raw customer data."},
    {"key": "correlation", "order": 9, "title": "Context + cross-bank evidence correlation",
     "actor": "system", "description": "Returned reports are linked against each other and the transaction trail."},
    {"key": "report_generated", "order": 10, "title": "AI-generated investigation report",
     "actor": "system", "description": "Findings are drafted into an explainable narrative with confidence and stated gaps."},
    {"key": "risk_assessment", "order": 11, "title": "Risk assessment",
     "actor": "system", "description": "Evidence is scored for escalation priority — as a flag, never a verdict."},
    {"key": "decision", "order": 12, "title": "Human / bank investigator decision",
     "actor": "human", "description": "A named investigator reviews the report and records the decision and its rationale."},
]

DECISION_OPTIONS = [
    {"value": "close_explained", "label": "Close — activity explained",
     "description": "The context or report explains the pattern.", "resulting_status": "closed"},
    {"value": "request_more_context", "label": "Request more context",
     "description": "Hold the case open for specific missing information.", "resulting_status": "context_verification"},
    {"value": "continue_investigation", "label": "Continue investigation",
     "description": "Keep the case open for further analysis.", "resulting_status": "investigation"},
    {"value": "escalate_compliance", "label": "Escalate to compliance / FIU",
     "description": "Refer the case with the report attached.", "resulting_status": "escalated"},
]


@pipeline_bp.route("/api/pipeline/flow", methods=["GET"])
@login_required
def pipeline_flow():
    """Return the stage list, live thresholds and the caller's decision options."""
    settings = get_settings(get_db())
    user = current_user()
    return jsonify({
        "stages": STAGES,
        "anomaly_threshold": settings.get("anomaly_threshold", ANOMALY_THRESHOLD),
        "investigation_threshold": settings.get("investigation_threshold", INVESTIGATION_THRESHOLD),
        "decision_options": _allowed_decision_options(user.get("role")),
        "all_decision_options": DECISION_OPTIONS,
        "can_escalate": can("cases:decide"),
    })


@pipeline_bp.route("/api/pipeline/run/<case_id>", methods=["POST"])
@login_required
def pipeline_run(case_id):
    """Run the pipeline for an existing case (stages 5-12)."""
    db = get_db()
    user = current_user()
    case = get_case(db, case_id)
    if not case:
        return jsonify({"error": "Case not found"}), 404

    allowed, reason = case_access(case, user)
    if not allowed:
        audit.record(db, user, "access_denied", target=case_id, detail=reason)
        return jsonify({"error": reason, "code": "forbidden"}), 403
    if not can("cases:investigate"):
        return jsonify({"error": "Your role cannot run investigations.", "code": "forbidden"}), 403

    case = serialize_doc(case)  # Convert ObjectId before use
    settings = get_settings(db)
    anomaly_threshold = settings.get("anomaly_threshold", ANOMALY_THRESHOLD)

    # Graph expansion. A case starts from the subject, but the pattern usually
    # reaches accounts held at other banks — those banks hold part of the evidence
    # and must be identified before any request goes out. Without this step a case
    # opened from a single transaction would contact one bank and see one bank's
    # data, which is the blind spot the platform exists to close.
    #
    # Depth is a scope decision, so it is bounded: an administrator sets the default,
    # a run may ask for a different one, and both are clamped to the same cap. What was
    # used is recorded with the stage so a reviewer can see how wide the walk was.
    depth = resolve_depth((request.get_json(silent=True) or {}).get("max_hops"),
                          default=settings.get("graph_max_hops"))
    network = expand_network(db, case.get("entity_ids", []), max_hops=depth)
    subject_ids = network["subject_ids"]
    entity_ids = network["entity_ids"]
    transactions = serialize_doc(list(db.transactions.find({"entity_id": {"$in": entity_ids}}).sort("timestamp", 1)))
    entities = {e["id"]: e for e in serialize_doc(list(db.entities.find()))}
    from config import BANKS

    # Build trace for stages 1-4 (already done)
    score = case.get("score", 0)

    # The gate line has to report the actual comparison. It used to say "YES"
    # unconditionally, so a 5% case rendered "YES — 5% clears the 35% threshold".
    gate_cleared = score >= anomaly_threshold
    gate_summary = (
        f"YES — {score * 100:.0f}% meets the {anomaly_threshold * 100:.0f}% threshold"
        if gate_cleared else
        f"NO — {score * 100:.0f}% is below the {anomaly_threshold * 100:.0f}% threshold; "
        f"the pipeline continues because an investigator opened this case explicitly"
    )

    trace = [
        {"key": "transaction", "order": 1, "title": "Transaction occurs", "actor": "system",
         "status": "done", "summary": f"{len(transactions)} transaction(s) under review"},
        {"key": "initial_analysis", "order": 2, "title": "Initial AI analysis", "actor": "system",
         "status": "done", "summary": f"Activity scores {score * 100:.0f}%"},
        {"key": "anomaly_gate", "order": 3, "title": "Meaningful anomaly or pattern?", "actor": "system",
         "status": "done", "summary": gate_summary},
        {"key": "case_created", "order": 4, "title": "Investigation case created", "actor": "system",
         "status": "done", "summary": f"Case {case_id} on file"},
    ]

    # Stage 5: Identify banks, and record why each one is in scope.
    bank_ids = sorted(set(t.get("bank_id") for t in transactions))
    bank_names = [BANKS.get(b, {}).get("name", b) for b in bank_ids]
    banks_in_scope = []
    for bank_id in bank_ids:
        holders = sorted({t["entity_id"] for t in transactions
                          if t.get("bank_id") == bank_id and t.get("entity_id")})
        banks_in_scope.append({
            "id": bank_id,
            "name": BANKS.get(bank_id, {}).get("name", bank_id),
            "country": BANKS.get(bank_id, {}).get("country", ""),
            "entity_ids": holders,
        })

    def _count(n, singular, plural=None):
        return f"{n} {singular if n == 1 else (plural or singular + 's')}"

    if network["added"]:
        shown = "; ".join(link["detail"] for link in network["links"][:4])
        remainder = len(network["links"]) - 4
        basis = (f"{_count(len(subject_ids), 'entity', 'entities')} named on the case reached "
                 f"{_count(len(network['added']), 'further entity', 'further entities')} within "
                 f"{_count(network['hops'], 'hop')}, which puts "
                 f"{_count(len(bank_ids), 'bank')} in scope. {shown}"
                 + (f"; and {_count(remainder, 'further link')}." if remainder > 0 else "."))
    else:
        basis = (f"{_count(len(subject_ids), 'entity', 'entities')} named on the case, with no wider "
                 f"network reachable from the recorded evidence — "
                 f"{_count(len(bank_ids), 'bank')} in scope.")

    trace.append({
        "key": "banks_identified", "order": 5, "title": "Relevant banks identified", "actor": "system",
        "status": "done",
        "summary": f"{len(bank_ids)} bank(s): {', '.join(bank_names)}",
        "detail": {
            "banks": banks_in_scope,
            "basis": basis,
            "subject_entity_ids": subject_ids,
            "added_entity_ids": network["added"],
            "expansion": network["links"],
            "hops": network["hops"],
            "max_hops": depth,
        },
    })

    # Stage 6: Send request
    route = case.get("status", "investigation")
    if route == "investigation":
        request_obj = create_investigation_request(
            entities=entity_ids,
            banks=bank_ids,
            reason="Coordinated cross-bank fund movement pattern detected.",
            priority="high",
        )
    else:
        # A context request is about the transaction that raised the case, so anchor
        # on the trigger rather than whichever transaction happens to sort last in
        # the expanded network.
        anchor = next((t for t in transactions
                       if t.get("id") == case.get("trigger_transaction_id")), None)
        if anchor is None:
            subject_txns = [t for t in transactions if t.get("entity_id") in set(subject_ids)]
            anchor = (subject_txns or transactions)[-1] if transactions else {}
        request_obj = create_context_request(
            transaction_id=anchor.get("id", ""),
            requesting_bank="system",
            target_bank=anchor.get("bank_id", ""),
            entity_id=anchor.get("entity_id", ""),
            reason="Transaction flagged for context verification.",
        )

    trace.append({
        "key": "request_sent", "order": 6, "title": "Investigation request sent", "actor": "system",
        "status": "done",
        "summary": f"Request {request_obj['request_id']} sent to {len(bank_ids)} bank(s)",
        "detail": {"request": request_obj},
    })

    # Stage 7: Bank analysis
    request_type = "investigation" if route == "investigation" else "context_verification"
    reports = []
    for bid in bank_ids:
        raw = get_mock_response(bid, request_type, request_obj, subject_ids[0] if subject_ids else None)
        reports.append({
            "request_id": request_obj["request_id"],
            "responding_bank": bid,
            "responding_bank_name": BANKS.get(bid, {}).get("name", bid),
            "status": raw.get("status", "completed"),
            "data": raw.get("data", {}),
        })

    trace.append({
        "key": "bank_analysis", "order": 7, "title": "Banks analyze their data", "actor": "bank",
        "status": "done",
        "summary": f"{len(reports)} bank(s) searched their records",
    })

    # Stage 8: Reports returned
    trace.append({
        "key": "reports_returned", "order": 8, "title": "Structured reports returned", "actor": "bank",
        "status": "done",
        "summary": f"{sum(1 for r in reports if r['status'] == 'completed')}/{len(reports)} report(s) returned",
        "detail": {"reports": reports},
    })

    # Store reports, and tell compliance something arrived at the case
    for report in reports:
        report["case_id"] = case_id
        create_bank_report(db, report)
        update_service.post(
            db, case, user, "bank_report",
            title=f"{report['responding_bank_name']} returned a report",
            description=(report.get("data", {}).get("recent_activity_summary")
                         or "Structured bank response received."),
            metadata={"request_id": report.get("request_id"),
                      "responding_bank": report.get("responding_bank"),
                      "status": report.get("status")},
        )

    # Stage 9: Correlation
    findings = _correlate_evidence(transactions, reports, entities, BANKS)
    trace.append({
        "key": "correlation", "order": 9, "title": "Cross-bank evidence correlation", "actor": "system",
        "status": "done",
        "summary": f"{len(findings)} finding(s) identified",
        "detail": {"findings": findings},
    })

    # Stage 10: Report generated
    report_data = _generate_report(case, transactions, findings, reports, entities, BANKS, route,
                                   scope={
                                       "entity_ids": entity_ids,
                                       "subject_entity_ids": subject_ids,
                                       "added_entity_ids": network["added"],
                                       "bank_ids": bank_ids,
                                   })
    trace.append({
        "key": "report_generated", "order": 10, "title": "Investigation report drafted", "actor": "system",
        "status": "done",
        "summary": f"Report {report_data['report_id']} drafted — {len(report_data['sections'])} sections",
        "detail": {"report": report_data},
    })

    # Stage 11: Risk assessment
    trace.append({
        "key": "risk_assessment", "order": 11, "title": "Risk assessment", "actor": "system",
        "status": "done",
        "summary": f"Risk {score * 100:.0f}% — {report_data['recommendation']}",
        "detail": {"score": score, "recommendation": report_data["recommendation"]},
    })

    # Stage 12: Pending decision
    trace.append({
        "key": "decision", "order": 12, "title": "Human decision", "actor": "human",
        "status": "pending",
        "summary": "Waiting for investigator's decision",
    })

    # Store pipeline state. The expanded network is persisted too: the case genuinely
    # grew, and the case list, the case header and any later run should read the same
    # scope the pipeline just reviewed rather than the one it started with.
    updates = {
        "pipeline_trace": trace,
        "pipeline_report": report_data,
        "pipeline_findings": findings,
    }
    # The bank list always becomes the evidence-based one. A case can name an entity whose
    # account holds no records relevant to the pattern, and contacting that bank would ask
    # it to search records it does not have — the case card and the pipeline should not
    # disagree about who was asked.
    updates["bank_ids"] = bank_ids

    if network["added"]:
        updates["entity_ids"] = entity_ids
    # Recorded on every run, not only when something was added: the scope a case was
    # actually walked to is a fact about that run, and "nothing further was reachable"
    # is exactly the sort of thing a later reviewer needs to see.
    updates["network_expansion"] = {
        "subject_entity_ids": subject_ids,
        "added_entity_ids": network["added"],
        "links": network["links"],
        "hops": network["hops"],
        "max_hops": depth,
        "expanded_at": datetime.utcnow().isoformat(),
    }
    update_case(db, case_id, updates)

    audit.record(db, user, "action", target=case_id, case_id=case_id,
                 resource_type="investigation_case", resource_id=case_id,
                 detail=f"Ran the investigation pipeline — {len(findings)} finding(s)",
                 metadata={"route": route, "banks": bank_ids})

    # What just came back becomes case evidence and an investigation update.
    filed = evidence.file_case_baseline(db, case)
    update_service.post(
        db, case, user, "bank_report",
        title=f"Bank responses received — {len(reports)} report(s)",
        description=(f"{', '.join(r['responding_bank_name'] for r in reports)} responded; "
                     f"{len(findings)} correlation finding(s) recorded."),
        metadata={"report_ids": [r.get("request_id") for r in reports],
                  "evidence_filed": [i["id"] for i in filed]},
    )
    for finding in findings:
        update_service.post(
            db, case, user, "finding",
            title=f"Finding — {finding.get('title')}",
            description=f"Strength: {finding.get('strength')} ({finding.get('kind')})",
            metadata={"finding_id": finding.get("id"), "strength": finding.get("strength")},
        )

    return jsonify(serialize_doc({
        "case_id": case_id,
        "trace": trace,
        "report": report_data,
        "findings": findings,
        "status": case.get("status"),
    }))


@pipeline_bp.route("/api/cases/<case_id>/decision", methods=["POST"])
@login_required
def record_decision(case_id):
    """Stage 12: Record the investigator's decision."""
    db = get_db()
    user = current_user()
    case = get_case(db, case_id)
    if not case:
        return jsonify({"error": "Case not found"}), 404

    allowed, reason = case_access(case, user)
    if not allowed:
        audit.record(db, user, "access_denied", target=case_id, detail=reason)
        return jsonify({"error": reason, "code": "forbidden"}), 403

    case = serialize_doc(case)  # Convert ObjectId
    settings = get_settings(db)

    data = request.json or {}
    decision = data.get("decision")
    rationale = (data.get("rationale") or "").strip()

    if not rationale and settings.get("require_decision_rationale", True):
        return jsonify({"error": "Rationale is required"}), 400

    option = next((o for o in DECISION_OPTIONS if o["value"] == decision), None)
    if not option:
        return jsonify({"error": "Invalid decision"}), 400

    if option["value"] not in [o["value"] for o in _allowed_decision_options(user.get("role"))]:
        audit.record(db, user, "access_denied", target=case_id,
                     detail=f"Attempted '{option['label']}' without escalation rights")
        return jsonify({
            "error": "Escalation to compliance / FIU is restricted to compliance officers and administrators.",
            "code": "forbidden",
            "required_permission": "cases:decide",
        }), 403

    # Attribution comes from the session: a decision is signed by whoever is signed in and
    # cannot be recorded in someone else's name. A client-supplied name that disagrees with
    # the session is an attempt to launder the attribution rather than a rename, so it is
    # refused and written to the trail.
    session_name = (user.get("name") or "").strip()
    claimed = (data.get("investigator") or "").strip()
    if claimed and session_name and claimed != session_name:
        audit.record(db, user, "access_denied", target=case_id, case_id=case_id,
                     detail=f"Attempted to record a decision in the name '{claimed}'")
        return jsonify({
            "error": (f"A decision is recorded in the name of the signed-in investigator "
                      f"({session_name})."),
            "code": "attribution_mismatch",
        }), 403

    investigator = session_name or (user.get("username") or "").strip()
    if not investigator:
        return jsonify({
            "error": "A decision must be attributed to a named investigator.",
            "code": "investigator_required",
        }), 400

    # Stage order: the decision is stage 12 and rests on the stage-10 report. A case that has
    # never been through the pipeline has nothing to decide on, and recording a decision here
    # would leave the audit trail pointing at a verdict with no evidence behind it.
    if not (case.get("pipeline_report") or {}).get("report_id"):
        audit.record(db, user, "access_denied", target=case_id, case_id=case_id,
                     detail="Attempted to record a decision with no investigation report")
        return jsonify({
            "error": ("There is no investigation report on this case yet — run the pipeline "
                      "before recording a decision."),
            "code": "report_required",
        }), 409

    decision_record = {
        "case_id": case_id,
        "decision": option["value"],
        "label": option["label"],
        "resulting_status": option["resulting_status"],
        "investigator": investigator,
        "user_id": user.get("id"),
        "username": user.get("username"),
        "actor_role": user.get("role"),
        "rationale": rationale,
        "decided_at": datetime.utcnow().isoformat(),
    }
    create_decision(db, decision_record)
    update_case(db, case_id, {"status": option["resulting_status"]})

    # Update trace
    trace = case.get("pipeline_trace", [])
    trace = [s for s in trace if s["key"] != "decision"]
    trace.append({
        "key": "decision", "order": 12, "title": "Human decision", "actor": "human",
        "status": "done",
        "summary": f"{investigator} decided: {option['label']}",
        "detail": decision_record,
    })
    update_case(db, case_id, {"pipeline_trace": trace})

    audit.record(db, user, "decision", target=case_id, case_id=case_id,
                 resource_type="investigation_case", resource_id=case_id,
                 detail=option["label"], reason=rationale,
                 metadata={"rationale": rationale, "resulting_status": option["resulting_status"]})
    update_service.post(
        db, case, user, "status_change",
        title=f"Decision recorded — {option['label']}",
        description=rationale or f"Recorded by {user['name']}",
        metadata={"decision": option["value"], "resulting_status": option["resulting_status"]},
    )

    return jsonify(serialize_doc({"decision": decision_record, "status": option["resulting_status"]}))


# ── Helpers ──────────────────────────────────────────────────────────────────

def _correlate_evidence(transactions, reports, entities, banks):
    """Cross-reference evidence from multiple banks."""
    findings = []

    # Shared counterparties
    by_cp = {}
    for t in transactions:
        cp = t.get("counterparty", "Unknown")
        if cp != "Unknown":
            by_cp.setdefault(cp, set()).add(t["bank_id"])

    for cp, bank_set in by_cp.items():
        if len(bank_set) > 1:
            findings.append({
                "id": f"f{len(findings)+1}",
                "kind": "shared_counterparty",
                "title": f"'{cp}' appears on {len(bank_set)} banks",
                "strength": "corroborated",
            })

    # Ownership links from reports
    for report in reports:
        if report["data"].get("beneficial_ownership_link"):
            findings.append({
                "id": f"f{len(findings)+1}",
                "kind": "ownership_link",
                "title": f"{report['responding_bank_name']}: beneficial ownership link detected",
                "strength": "single_source",
            })

    # Cross-bank entity references
    for report in reports:
        for linked in report["data"].get("entities_linked", []):
            host_banks = set(t["bank_id"] for t in transactions if t["entity_id"] == linked)
            if host_banks and report["responding_bank"] not in host_banks:
                findings.append({
                    "id": f"f{len(findings)+1}",
                    "kind": "cross_bank_reference",
                    "title": f"{report['responding_bank_name']} references entity at another bank",
                    "strength": "corroborated",
                })

    return findings


def _generate_report(case, transactions, findings, reports, entities, banks, route, scope=None):
    """Generate the investigation report.

    `scope` carries the expanded network the run actually reviewed. The case record
    holds only the entities named when it was opened, so reporting those numbers
    would understate what the investigation covered.
    """
    report_id = f"rpt_{uuid.uuid4().hex[:10]}"
    score = case.get("score", 0)

    scope = scope or {}
    entity_ids = scope.get("entity_ids") or case.get("entity_ids", [])
    bank_ids = scope.get("bank_ids") or case.get("bank_ids", [])
    named_scope = scope.get("subject_entity_ids") or case.get("entity_ids", [])
    added = scope.get("added_entity_ids") or []

    def _count(n, singular, plural=None):
        return f"{n} {singular if n == 1 else (plural or singular + 's')}"

    summary = (f"Investigation case {case['id']} involves {_count(len(entity_ids), 'entity', 'entities')} "
               f"across {_count(len(bank_ids), 'bank')}. Activity score: {score * 100:.0f}%.")
    if added:
        named_count = len(named_scope)
        summary += (f" {_count(named_count, 'entity', 'entities')} "
                    f"{'was' if named_count == 1 else 'were'} named on the case and graph expansion "
                    f"brought in {_count(len(added), 'further entity', 'further entities')}, "
                    f"at which point {_count(len(bank_ids), 'bank')} hold records relevant to the pattern.")

    # Build sections
    sections = [
        {
            "title": "Executive Summary",
            "body": [summary],
        },
        {
            "title": "Evidence Findings",
            "bullets": [f"[{f['strength']}] {f['title']}" for f in findings],
        },
    ]

    # Add context section for hospital scenario
    if route == "context_verification":
        hospital_report = next((r for r in reports if "apollo" in r["data"].get("additional_context", "").lower()), None)
        if hospital_report:
            ctx = hospital_report["data"]
            sections.append({
                "title": "Context Returned by Bank",
                "bullets": [
                    f"Relationship: {ctx.get('entity_relationship_status', 'N/A')}",
                    f"Tenure: {ctx.get('account_tenure', 'N/A')}",
                    f"Context: {ctx.get('additional_context', 'N/A')}",
                ],
            })

    # Confidence
    pattern_confidence = min(0.95, 0.4 + len(findings) * 0.1)
    intent_confidence = 0.2 if route == "investigation" else 0.8
    overall_confidence = 0.6 * pattern_confidence + 0.4 * intent_confidence

    return {
        "report_id": report_id,
        "case_id": case["id"],
        "generated_at": datetime.utcnow().isoformat(),
        "route": route,
        "score": score,
        "recommendation": "Investigate" if score > 0.65 else "Context verification" if score > 0.35 else "No action",
        "sections": sections,
        "confidence": {
            "overall": round(overall_confidence, 2),
            "pattern": round(pattern_confidence, 2),
            "intent": round(intent_confidence, 2),
        },
        "disclaimer": "Context Guard flags and correlates for investigation. It does not determine guilt.",
    }
