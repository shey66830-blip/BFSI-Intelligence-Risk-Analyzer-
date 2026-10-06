"""
Context Guard — Ingest Routes

Flask blueprint for the live transaction feed (stages 1-4 of the pipeline).
"""

from flask import Blueprint, jsonify, request
from datetime import datetime
import uuid

from config import get_db, BANKS, ANOMALY_THRESHOLD, INVESTIGATION_THRESHOLD
from middleware import current_user, login_required
from models import serialize_doc, create_case, create_transaction, upsert_entity, get_entity
from services import audit
from services.settings import get_settings

ingest_bp = Blueprint("ingest", __name__)


# ── Live-ingest scenario definitions ──────────────────────────────────────

def _txn(offset_minutes, entity_id, bank_id, type_, amount, currency,
         description, category, counterparty, device_id, country):
    return {
        "id": f"txn_live_{uuid.uuid4().hex[:8]}",
        "timestamp": (datetime.utcnow()).isoformat(),
        "entity_id": entity_id,
        "bank_id": bank_id,
        "type": type_,
        "amount": amount,
        "currency": currency,
        "description": description,
        "category": category,
        "counterparty": counterparty,
        "device_id": device_id,
        "country": country,
        "consent_given": True,
    }


SCENARIOS = {
    "routine": {
        "label": "Everyday card spend on an established account",
        "transaction": lambda: _txn(0, "e_priya", "bank_a", "debit", 850, "INR",
            "Amazon India - Groceries", "groceries", "Amazon India", "d1", "IN"),
    },
    "high_value": {
        "label": "Large payment with contextual explanation (hospital scenario)",
        "transaction": lambda: _txn(0, "e_rajesh", "bank_a", "debit", 300000, "INR",
            "Apollo Hospitals - Cardiac Procedure Co-pay", "medical",
            "Apollo Hospitals Enterprise Ltd", "d4", "IN"),
    },
    "coordinated": {
        "label": "Cross-bank coordinated activity pattern",
        "transaction": lambda: _txn(0, "e_vikram", "bank_b", "debit", 250000, "INR",
            "Transfer to unknown account", "transfer",
            "Unknown Recipient", "d2", "IN"),
    },
}


def _score_transaction(txn, history, mitigate_medical=True):
    """Score a transaction against its account's historical baseline.
    
    Uses weighted accumulation — multiple moderate signals add up,
    rather than only the strongest signal counting.
    """
    entity_id = txn.get("entity_id")
    amounts = [h.get("amount", 0) for h in history if h.get("entity_id") == entity_id]
    if not amounts:
        return 0.35, [{"signal": "insufficient_history", "description": "No prior transactions", "severity": "medium"}], "insufficient_history"

    avg = sum(amounts) / len(amounts)
    std = (sum((a - avg) ** 2 for a in amounts) / len(amounts)) ** 0.5 if len(amounts) > 1 else avg * 0.3
    amount = txn.get("amount", 0)

    reasons = []
    weights = []  # collect individual weights, then blend

    # Signal 1: Amount outlier (z-score)
    if std > 0:
        z = (amount - avg) / std
        if z > 2.0:
            w = min(z / 6.0, 1.0)
            weights.append(w)
            reasons.append({
                "signal": "amount_outlier",
                "description": f"Amount {amount:,.0f} is {z:.1f} sigma above the mean {avg:,.0f}",
                "severity": "high" if z > 4 else "medium",
            })

    # Signal 2: Large amount absolute
    if amount > 100000:
        weights.append(0.4)
        reasons.append({
            "signal": "large_amount",
            "description": f"{amount:,.0f} exceeds 1,00,000 threshold",
            "severity": "medium",
        })

    # Signal 3: Unknown / new counterparty
    known_cps = set(h.get("counterparty", "") for h in history if h.get("entity_id") == entity_id)
    if txn.get("counterparty") and txn["counterparty"] not in known_cps:
        weights.append(0.15)
        reasons.append({
            "signal": "new_counterparty",
            "description": f"First transaction with '{txn['counterparty']}'",
            "severity": "low",
        })

    # Signal 4: Medical category — contextual explanation available (lowers effective risk)
    # The organisation can switch this mitigation off from Settings.
    if txn.get("category") == "medical" and amount > 100000:
        reasons.append({
            "signal": "medical_context_available",
            "description": "Medical payment — hospital context and insurance claim may explain",
            "severity": "low",
        })
        if mitigate_medical:
            # Adds a negative weight — the context mitigates risk, but not fully
            weights.append(-0.05)

    # Signal 5: Crypto
    if txn.get("category") == "crypto":
        weights.append(0.6)
        reasons.append({
            "signal": "crypto_offramp",
            "description": "Crypto exchange deposit detected",
            "severity": "high",
        })

    # Signal 6: Transfer to unknown recipient
    if txn.get("category") in ("transfer", "cash") and "unknown" in (txn.get("counterparty") or "").lower():
        weights.append(0.35)
        reasons.append({
            "signal": "unknown_recipient",
            "description": f"Funds sent to unverified recipient: {txn.get('counterparty')}",
            "severity": "high",
        })

    # Signal 7: Cash withdrawal (always suspicious at scale)
    if txn.get("category") == "cash" and amount > 50000:
        weights.append(0.25)
        reasons.append({
            "signal": "large_cash_withdrawal",
            "description": f"Cash withdrawal of {amount:,.0f}",
            "severity": "medium",
        })

    # Blend: use noisy-OR for positive signals, but cap to prevent runaway
    if not weights:
        return 0.0, reasons, "no_signals"

    # Separate positive and negative weights
    pos = [w for w in weights if w > 0]
    neg = [abs(w) for w in weights if w < 0]

    # Noisy-OR: 1 - product(1 - w) for positive signals
    if pos:
        noisy_or = 1.0
        for w in pos:
            noisy_or *= (1.0 - w)
        blended = 1.0 - noisy_or
    else:
        blended = 0.0

    # Apply mitigation from negative signals (medical context etc.)
    for nw in neg:
        blended = blended * (1.0 - nw)

    return min(blended, 1.0), reasons, "scored"


@ingest_bp.route("/api/pipeline/ingest", methods=["POST"])
@login_required
def pipeline_ingest():
    """Stages 1-4: a transaction arrives, is analysed, and may open a case."""
    db = get_db()
    user = current_user()
    settings = get_settings(db)
    anomaly_threshold = settings.get("anomaly_threshold", ANOMALY_THRESHOLD)
    investigation_threshold = settings.get("investigation_threshold", INVESTIGATION_THRESHOLD)
    data = request.json or {}
    scenario_name = data.get("scenario", "routine")

    scenario_def = SCENARIOS.get(scenario_name)
    if not scenario_def:
        return jsonify({"error": f"Unknown scenario: {scenario_name}"}), 400

    # Generate the transaction
    txn = scenario_def["transaction"]()

    # Collect historical transactions for this entity
    entity_id = txn["entity_id"]
    history = list(db.transactions.find({"entity_id": entity_id}))

    # Stage 1: Transaction recorded
    create_transaction(db, txn)
    entity = get_entity(db, entity_id)
    bank = BANKS.get(txn["bank_id"], {})
    txn = serialize_doc(txn)  # Convert ObjectId
    entity = serialize_doc(entity)

    trace = [
        {
            "key": "transaction", "order": 1, "title": "Transaction occurs", "actor": "system",
            "status": "done",
            "summary": f"₹{txn['amount']:,.0f} — {txn['description']}",
            "detail": {
                "transaction": txn,
                "entity": entity or {"id": entity_id, "name": entity_id},
                "bank": bank,
                "history_size": len(history),
            },
        }
    ]

    # Stage 2: AI analysis
    score, reasons, method = _score_transaction(
        txn, history, mitigate_medical=settings.get("hospital_context_mitigation", True)
    )
    trace.append({
        "key": "initial_analysis", "order": 2, "title": "Initial AI analysis", "actor": "system",
        "status": "done",
        "summary": f"Score: {score * 100:.0f}% — {len(reasons)} signal(s)",
        "detail": {
            "transaction_score": score,
            "activity_score": score,
            "reasons": reasons,
            "method": f"Scored against {len(history)} prior transactions for {entity_id}",
        },
    })

    # Stage 3: Anomaly gate
    if score >= investigation_threshold:
        route = "investigation"
        decision = "investigate"
    elif score >= anomaly_threshold:
        route = "context_verification"
        decision = "investigate"
    else:
        route = "no_action"
        decision = "stand_down"

    trace.append({
        "key": "anomaly_gate", "order": 3, "title": "Meaningful anomaly or pattern?", "actor": "system",
        "status": "done",
        "summary": f"{'YES' if decision == 'investigate' else 'NO'} — {score * 100:.0f}% vs {anomaly_threshold * 100:.0f}% threshold",
        "detail": {
            "score": score,
            "threshold": anomaly_threshold,
            "investigation_threshold": investigation_threshold,
            "decision": decision,
            "route": route,
            "top_reasons": reasons[:3],
        },
    })

    # Stage 4: Case creation (only if gate opens)
    case = None
    if decision == "investigate":
        case_id = f"case_live_{uuid.uuid4().hex[:8]}"
        case = {
            "id": case_id,
            "title": f"Live: {txn['description'][:50]}",
            "description": f"Auto-created from live ingest — {txn['counterparty']}, ₹{txn['amount']:,.0f}",
            "entity_ids": [entity_id],
            "bank_ids": [txn["bank_id"]],
            "status": route,
            "score": score,
            "trigger_transaction_id": txn["id"],
            "origin": "live_ingest",
            "scenario": scenario_name,
            "created_by": user.get("id"),
        }
        # An analyst who simulates a transaction keeps the resulting case, so the
        # end-to-end demo still works under assignment-based scoping.
        if user.get("role") == "analyst":
            case["assigned_to"] = user["id"]
            case["assigned_to_name"] = user.get("name")
            db.users.update_one({"id": user["id"]}, {"$addToSet": {"assigned_case_ids": case_id}})
        create_case(db, case)
        trace.append({
            "key": "case_created", "order": 4, "title": "Investigation case created", "actor": "system",
            "status": "done",
            "summary": f"Case {case_id} opened — routing to {route.replace('_', ' ')}",
            "detail": {
                "case_id": case_id,
                "status": route,
                "trigger_transaction_id": txn["id"],
                "entity_ids": [entity_id],
                "bank_ids": [txn["bank_id"]],
                "why": reasons,
            },
        })
    else:
        trace.append({
            "key": "case_created", "order": 4, "title": "Investigation case created", "actor": "system",
            "status": "skipped",
            "summary": "Gate closed — no case created",
        })

    audit.record(db, user, "action", target=(case or {}).get("id"),
                 detail=f"Simulated '{scenario_name}' transaction — routed to {route.replace('_', ' ')}",
                 metadata={"score": score, "case_created": case is not None})

    return jsonify({
        "scenario": scenario_name,
        "transaction": serialize_doc(txn),
        "analysis": {"score": score, "reasons": reasons},
        "route": route,
        "case_created": case is not None,
        "case": serialize_doc(case),
        "trace": trace,
        "context_note": scenario_def["label"],
    })
