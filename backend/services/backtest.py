"""
Context Guard — Threshold Backtest

A threshold is a judgement about how much suspicion is worth a person's time. Changing
one should be argued with evidence rather than by feel, so this replays the demonstration
scenarios and the seeded cases through the gate's **own** scoring function at a grid of
candidate thresholds and reports which subjects would have been routed differently.

It deliberately reuses `routes.ingest`'s scorer and scenario definitions. A backtest that
scored with different code would be measuring the backtest, not the gate — and the whole
point is to say what the gate would actually do.
"""

from datetime import datetime

from config import ANOMALY_THRESHOLD, INVESTIGATION_THRESHOLD

# The grid the console offers by default. Coarse on purpose: the interesting question is
# "does this scenario still open at all", not the third decimal place.
DEFAULT_ANOMALY_GRID = [0.20, 0.35, 0.50, 0.65, 0.80, 0.98]
DEFAULT_INVESTIGATION_GRID = [0.50, 0.65, 0.80, 0.99]

# What each subject is designed to demonstrate. The gate is doing its job when it routes
# these the way the story requires — the hospital payment opens a context case, the
# coordinated pattern escalates, and everyday spend is left alone.
EXPECTED = {
    "routine": "no_action",
    "high_value": "context_verification",
    "coordinated": "investigation",
    "case_1": "no_action",
    "case_2": "context_verification",
    "case_3": "investigation",
}

SEEDED_CASES = ("case_1", "case_2", "case_3")


def route_for(score, anomaly_threshold, investigation_threshold):
    """The single place the gate's routing rule is expressed for a backtest."""
    if score >= investigation_threshold:
        return "investigation"
    if score >= anomaly_threshold:
        return "context_verification"
    return "no_action"


def observations(db, mitigate_medical=True):
    """Score every scenario and seeded case with the gate's own scorer.

    Reuses the live scoring function so the numbers here are the numbers the platform
    would produce, not an approximation of them.
    """
    from routes.ingest import SCENARIOS, _score_transaction

    rows = []
    for name, spec in SCENARIOS.items():
        txn = spec["transaction"]()
        history = list(db.transactions.find({"entity_id": txn["entity_id"]}))
        score, reasons, method = _score_transaction(
            txn, history, mitigate_medical=mitigate_medical)
        rows.append({
            "subject": name, "kind": "scenario", "label": spec["label"],
            "score": round(float(score), 4), "signals": len(reasons), "method": method,
            "top_signal": (reasons[0]["signal"] if reasons else None),
            "expected_route": EXPECTED.get(name),
        })

    for case_id in SEEDED_CASES:
        case = db.cases.find_one({"id": case_id})
        if not case:
            continue
        rows.append({
            "subject": case_id, "kind": "case",
            "label": case.get("title") or case_id,
            "score": round(float(case.get("score") or 0.0), 4),
            "signals": None, "method": "case score as seeded",
            "top_signal": None, "expected_route": EXPECTED.get(case_id),
        })
    return rows


def _pair(anomaly, investigation):
    return round(float(anomaly), 4), round(float(investigation), 4)


def evaluate(rows, anomaly, investigation):
    """Route every observation at one threshold pair and report what disagreed."""
    predictions = []
    for row in rows:
        route = route_for(row["score"], anomaly, investigation)
        predictions.append({**row, "route": route,
                            "agrees": route == row["expected_route"]})
    agreed = sum(1 for p in predictions if p["agrees"])
    return {
        "anomaly_threshold": anomaly,
        "investigation_threshold": investigation,
        "subjects": len(predictions),
        "agreed": agreed,
        "accuracy": round(agreed / len(predictions), 3) if predictions else 0.0,
        "misrouted": [p["subject"] for p in predictions if not p["agrees"]],
        "predictions": predictions,
    }


def grid(db, anomaly_values=None, investigation_values=None, mitigate_medical=True):
    """Every valid threshold pair, scored. An investigation gate at or below the
    anomaly gate is dropped: it is not a configuration, it is a contradiction."""
    rows = observations(db, mitigate_medical=mitigate_medical)
    anomalies = sorted({_pair(a, 0)[0] for a in (anomaly_values or DEFAULT_ANOMALY_GRID)})
    investigations = sorted({_pair(0, i)[1]
                             for i in (investigation_values or DEFAULT_INVESTIGATION_GRID)})

    results = []
    for anomaly in anomalies:
        for investigation in investigations:
            if investigation <= anomaly:
                continue
            results.append(evaluate(rows, anomaly, investigation))
    return rows, results


def parse_grid(raw, default):
    """Read a comma-separated threshold list from a query string."""
    if not raw:
        return list(default)
    values = []
    for part in str(raw).split(","):
        try:
            values.append(float(part.strip()))
        except (TypeError, ValueError):
            continue
    return values or list(default)


def report(db, anomaly_values=None, investigation_values=None, current=None,
           mitigate_medical=True):
    """The whole backtest: what scored, how each pair routs it, and what to change to."""
    from services.settings import get_settings

    settings = get_settings(db) if current is None else current
    live_anomaly = float(settings.get("anomaly_threshold", ANOMALY_THRESHOLD))
    live_investigation = float(settings.get("investigation_threshold", INVESTIGATION_THRESHOLD))

    rows, results = grid(db, anomaly_values, investigation_values, mitigate_medical)
    live = evaluate(rows, round(live_anomaly, 4), round(live_investigation, 4)) \
        if live_investigation > live_anomaly else None
    best = max(results, key=lambda r: (r["accuracy"], r["anomaly_threshold"],
                                       r["investigation_threshold"]), default=None)

    # The scenarios the story depends on, and the live score for each.
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "observations": rows,
        "current": {
            "anomaly_threshold": round(live_anomaly, 4),
            "investigation_threshold": round(live_investigation, 4),
            "result": live,
        },
        "best": best,
        "results": results,
        "note": ("A backtest is not a recommendation. It says what the gate would do at "
                 "each threshold against the scenarios the demonstration is built on; "
                 "choosing one is a judgement about how much suspicion is worth a "
                 "person's time."),
    }
