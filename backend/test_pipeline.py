"""
End-to-end checks for the Context Guard investigation pipeline.

Run with:  cd backend && python test_pipeline.py

Exercises the full flow for each scenario and for the curated demo cases, and
prints the drafted report so the narrative can be reviewed by eye.

The pipeline endpoints sit behind the same authentication layer as the rest of
the API, so the suite signs in first and sends the bearer token on every call.
It also re-seeds the demo dataset before running, because each ingest adds
transactions that shift the behavioural baseline the scorer measures against —
without the reset, a second consecutive run scores against the first run's data.
"""

import json
import sys

# Reports contain non-ASCII characters (→, ↔, ·); Windows consoles default to cp1252.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app import create_app, init_database
from services.reset import reset_demo_state


def check(label, condition, detail=""):
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f" — {detail}" if detail else ""))
    if not condition:
        raise AssertionError(label)


def stage_map(trace):
    return {s["key"]: s for s in trace}


class AuthedClient:
    """The Flask test client with the caller's bearer token on every request.

    Wrapping rather than a helper per call site keeps the body of the suite
    identical to what it was before the API required authentication.
    """

    def __init__(self, client, token):
        self._client = client
        self._headers = {"Authorization": f"Bearer {token}"}

    def get(self, *args, **kwargs):
        kwargs.setdefault("headers", self._headers)
        return self._client.get(*args, **kwargs)

    def post(self, *args, **kwargs):
        kwargs.setdefault("headers", self._headers)
        return self._client.post(*args, **kwargs)


def main():
    print("── Bootstrapping ─────────────────────────────────────────────")
    reset_demo_state()
    init_database()
    app = create_app()
    raw = app.test_client()

    anon = raw.get("/api/pipeline/flow")
    check("an unauthenticated caller is refused", anon.status_code == 401,
          f"HTTP {anon.status_code}")

    login = raw.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    payload = login.get_json() or {}
    check("the pipeline suite can sign in", login.status_code == 200,
          f"HTTP {login.status_code}")
    print(f"        signed in as {payload['user']['name']} ({payload['user']['role_label']})")
    signed_in_name = payload["user"]["name"]

    client = AuthedClient(raw, payload["token"])

    # ---------------------------------------------------------------- flow meta
    flow = client.get("/api/pipeline/flow").get_json()
    check("flow exposes 12 stages", len(flow["stages"]) == 12, f"{len(flow['stages'])} stages")
    check("stage order runs 1..12", [s["order"] for s in flow["stages"]] == list(range(1, 13)))
    check("decision options exposed", len(flow["decision_options"]) == 4)

    # -------------------------------------------------------- stages 1-4 per route
    ingest = {}
    for scenario in ("routine", "high_value", "coordinated"):
        body = client.post("/api/pipeline/ingest", json={"scenario": scenario}).get_json()
        ingest[scenario] = body
        stages = stage_map(body["trace"])
        check(f"[{scenario}] trace covers stages 1-4", stages["case_created"]["order"] == 4)
        print(f"        route={body['route']} case={body['case_created']} "
              f"score={body['analysis']['score']}")

    check("routine activity stays below the gate",
          ingest["routine"]["route"] == "no_action" and not ingest["routine"]["case_created"],
          f"score {ingest['routine']['analysis']['score']}")
    # Ingest returns stages 1-4; the remaining eight are appended by /api/pipeline/run.
    # When the gate closes, the case-creation stage is the one that stands down.
    check("routine pipeline marks case creation skipped",
          stage_map(ingest["routine"]["trace"])["case_created"]["status"] == "skipped")

    check("high-value wire routes to context verification",
          ingest["high_value"]["route"] == "context_verification" and ingest["high_value"]["case_created"],
          f"score {ingest['high_value']['analysis']['score']}")
    check("coordinated pattern routes to investigation",
          ingest["coordinated"]["route"] == "investigation" and ingest["coordinated"]["case_created"],
          f"score {ingest['coordinated']['analysis']['score']}")

    coord_case = ingest["coordinated"]["case"]
    check("gate reasons are explained",
          len(ingest["coordinated"]["trace"][2]["detail"]["top_reasons"]) > 0)

    # --------------------------------------------------------------- stages 5-11
    run = client.post(f"/api/pipeline/run/{coord_case['id']}").get_json()
    stages = stage_map(run["trace"])
    check("run returns a full 12-stage trace", len(run["trace"]) == 12, f"{len(run['trace'])} stages")

    # Stage 5 is the graph-expansion step. The case names one entity, so without it
    # the pipeline would contact one bank and see a fraction of the pattern — the
    # blind spot the platform exists to close.
    scope = stages["banks_identified"]["detail"]
    banks = scope["banks"]
    check("the entity named on the case is the subject of the expansion",
          scope["subject_entity_ids"] == coord_case["entity_ids"],
          f"{scope['subject_entity_ids']} vs {coord_case['entity_ids']}")
    check("expansion reaches accounts beyond the subject", len(scope["added_entity_ids"]) > 0,
          str(scope["added_entity_ids"]))
    check("every entity added is justified by a recorded link",
          len(scope["expansion"]) >= len(scope["added_entity_ids"]),
          f"{len(scope['expansion'])} link(s) for {len(scope['added_entity_ids'])} entity(ies)")
    check("expansion links name the link type and the transaction behind it",
          all(link.get("via") in ("counterparty", "shared_device") and link.get("detail")
              for link in scope["expansion"]),
          str([link.get("via") for link in scope["expansion"]]))
    check("banks are identified from the expanded network, not just the subject's bank",
          len(banks) >= 2, str([b["name"] for b in banks]))
    check("each bank in scope is tied to at least one named entity",
          all(b.get("entity_ids") for b in banks))
    check("the bank list states why each bank is in scope", bool(scope["basis"]),
          scope["basis"][:100])

    check("investigation request was structured",
          stages["request_sent"]["detail"]["request"]["type"] == "investigation")
    investigation = stages["request_sent"]["detail"]["request"]
    check("the request names the network it covers, not just the subject",
          set(investigation.get("entities_under_review", [])) ==
          set(scope["subject_entity_ids"] + scope["added_entity_ids"]),
          str(investigation.get("entities_under_review")))
    check("the request goes to every bank in scope",
          set(investigation.get("participating_banks", [])) ==
          {b["id"] for b in banks}, str(investigation.get("participating_banks")))
    check("every bank in scope returned a report",
          len(stages["reports_returned"]["detail"]["reports"]) == len(banks),
          f"{len(stages['reports_returned']['detail']['reports'])} report(s) for {len(banks)} bank(s)")

    # Corroboration is a cross-bank claim: it is only made when two independent
    # sources agree, and anything else is labelled as a single source.
    findings = run["findings"]
    check("cross-bank findings are produced", len(findings) >= 1, f"{len(findings)} finding(s)")
    check("every finding is labelled corroborated or single source",
          all(f.get("strength") in ("corroborated", "single_source") for f in findings),
          str([f.get("strength") for f in findings]))
    check("at least one finding is corroborated across banks",
          any(f.get("strength") == "corroborated" for f in findings))
    check("every finding carries a title that names what it is about",
          all(f.get("title") for f in findings))
    check("the correlation stage reports the same findings as the response",
          stages["correlation"]["detail"]["findings"] == findings)

    report = run["report"]
    check("report has sections", len(report["sections"]) >= 2,
          str([s["title"] for s in report["sections"]]))
    check("report disclaims guilt", "does not determine" in report["disclaimer"])
    check("report carries a recommendation", bool(report.get("recommendation")))
    confidence = report["confidence"]
    check("confidence separates pattern from intent",
          set(confidence) == {"overall", "pattern", "intent"}, str(sorted(confidence)))
    check("confidence dimensions are probabilities",
          all(0 <= value <= 1 for value in confidence.values()), str(confidence))

    risk = stages["risk_assessment"]["detail"]
    check("risk assessed", risk["score"] > 0.6, f"score {risk['score']}")
    check("the risk stage and the report agree on the score", risk["score"] == report["score"])
    check("decision stage still pending", stages["decision"]["status"] == "pending")

    # ------------------------------------------------------------ context branch
    # The hospital payment: the same ₹3,00,000 as the unexplained transfer above, but
    # a bank answers with the context that explains it.
    hv_case = ingest["high_value"]["case"]
    hv_run = client.post(f"/api/pipeline/run/{hv_case['id']}").get_json()
    hv_stages = stage_map(hv_run["trace"])
    context_request = hv_stages["request_sent"]["detail"]["request"]
    check("context branch uses a context request",
          context_request["type"] == "context_verification")
    check("context request is consent scoped",
          context_request["consent_required"] is True)
    check("the request is anchored on the transaction that raised the case",
          context_request["transaction_id"] == hv_case["trigger_transaction_id"],
          f"{context_request['transaction_id']} vs {hv_case['trigger_transaction_id']}")
    check("the request names the subject, not an entity reached by expansion",
          context_request["entity_id"] == hv_case["entity_ids"][0],
          f"{context_request['entity_id']} vs {hv_case['entity_ids'][0]}")
    check("the request asks for context fields, not for an accusation",
          "consent_status" in context_request.get("requested_fields", []),
          str(context_request.get("requested_fields")))

    bank_answer = json.dumps(hv_stages["reports_returned"]["detail"]["reports"][0]["data"])
    check("the bank explains the payment rather than only reporting it",
          "insurance" in bank_answer.lower() and "apollo" in bank_answer.lower(),
          bank_answer[:110])
    hv_risk = hv_stages["risk_assessment"]["detail"]["score"]
    check("the explained payment scores below the unexplained one",
          hv_risk < risk["score"], f"hospital {hv_risk} vs unexplained transfer {risk['score']}")

    # ------------------------------------------- gate closes on a monitored case
    quiet = client.post("/api/pipeline/run/case_1").get_json()
    quiet_stages = stage_map(quiet["trace"])
    check("low-risk case still returns a full 12-stage trace", len(quiet["trace"]) == 12)
    gate_line = quiet_stages["anomaly_gate"]["summary"]
    check("the gate line reports the comparison it actually made",
          gate_line.startswith("NO"), gate_line)
    check("the gate line names the threshold the case did not meet",
          f"{flow['anomaly_threshold'] * 100:.0f}%" in gate_line, gate_line)
    check("the gate line does not claim a low-risk case cleared the gate",
          f"{quiet['report']['score'] * 100:.0f}% meets" not in gate_line, gate_line)
    # Running an existing case stays available below the gate — an investigator asked
    # for it explicitly. Ingest is where the gate decides on its own (checked above).
    check("an explicitly run case below the gate is still processed",
          quiet_stages["banks_identified"]["status"] == "done")

    # -------------------------------------------------------- curated demo cases
    for case_id in ("case_2", "case_3"):
        body = client.post(f"/api/pipeline/run/{case_id}").get_json()
        check(f"[{case_id}] pipeline runs", len(body["trace"]) == 12)
        check(f"[{case_id}] report produced", bool(body["report"]["report_id"]))

        # A case can name an entity whose bank holds no records relevant to the pattern.
        # The card and the pipeline must not disagree about which banks were asked.
        curated_scope = stage_map(body["trace"])["banks_identified"]["detail"]
        curated = client.get(f"/api/cases/{case_id}").get_json()
        check(f"[{case_id}] the case's bank list matches the banks actually contacted",
              set(curated["bank_ids"]) == {b["id"] for b in curated_scope["banks"]},
              f"case {curated['bank_ids']} vs pipeline "
              f"{[b['id'] for b in curated_scope['banks']]}")
        check(f"[{case_id}] the report states the same scope as the pipeline",
              f"{len(curated_scope['banks'])} bank" in body["report"]["sections"][0]["body"][0],
              body["report"]["sections"][0]["body"][0][:110])

    # ---------------------------------------------------------------- stage 12
    bad = client.post(f"/api/cases/{coord_case['id']}/decision",
                      json={"decision": "escalate_compliance", "rationale": ""})
    check("decision requires a rationale", bad.status_code == 400, f"HTTP {bad.status_code}")

    bad = client.post(f"/api/cases/{coord_case['id']}/decision",
                      json={"decision": "declare_fraud", "rationale": "x"})
    check("a verdict of fraud is not an available decision", bad.status_code == 400,
          f"HTTP {bad.status_code}")

    # Attribution belongs to the session, not to the request body: a decision cannot be
    # signed in another person's name, however the caller spells it.
    bad = client.post(f"/api/cases/{coord_case['id']}/decision",
                      json={"decision": "continue_investigation",
                            "investigator": "A. Investigador", "rationale": "x"})
    check("a decision cannot be signed in another name", bad.status_code == 403,
          f"HTTP {bad.status_code}")
    check("the refused signature is explained",
          (bad.get_json() or {}).get("code") == "attribution_mismatch",
          (bad.get_json() or {}).get("code"))

    decision = client.post(
        f"/api/cases/{coord_case['id']}/decision",
        json={
            "decision": "continue_investigation",
            "rationale": "Cross-bank links corroborated; requesting beneficial ownership documents.",
        },
    ).get_json()
    check("the decision is attributed to the session identity",
          decision["decision"]["investigator"] == signed_in_name,
          decision["decision"]["investigator"])
    check("decision updates case status", decision["status"] == "investigation")
    check("decision reports the status it produced",
          decision["decision"]["resulting_status"] == "investigation")

    fetched = client.get(f"/api/cases/{coord_case['id']}").get_json()
    check("case detail carries the drafted report", bool(fetched["pipeline_report"]))
    check("case detail carries the decision",
          fetched["decision"]["decision"] == "continue_investigation")
    check("case detail carries the workflow position",
          bool((fetched.get("workflow") or {}).get("status")),
          str((fetched.get("workflow") or {}).get("status")))

    # The expansion is persisted, so the case list, the case header and any later run
    # all read the scope the pipeline actually reviewed.
    check("the case now records the network it was expanded to",
          set(fetched["entity_ids"]) == set(coord_case["entity_ids"] + scope["added_entity_ids"]),
          str(fetched["entity_ids"]))
    check("the case's bank list matches the banks the pipeline put in scope",
          set(fetched["bank_ids"]) == {b["id"] for b in banks}, str(fetched["bank_ids"]))
    check("the stored expansion keeps the links that justify it",
          bool((fetched.get("network_expansion") or {}).get("links")),
          str(fetched.get("network_expansion"))[:90])

    stats = client.get("/api/dashboard-stats").get_json()
    check("stats count auto-created cases", stats["total_cases"] >= 5, f"{stats['total_cases']} cases")

    # ------------------------------------------------------------- show the work
    print("\n" + "=" * 78)
    # ── Threshold backtest ────────────────────────────────────────
    # A threshold silently decides which cases a person ever sees, so a change comes
    # with the evidence that produced it rather than by feel.
    print("\n── Threshold backtest ──────────────────────────────────────")
    bt = client.get("/api/admin/threshold-backtest").get_json() or {}
    observations = bt.get("observations") or []
    subjects = {o["subject"]: o for o in observations}
    check("the backtest scores every scenario and seeded case",
          len(observations) == 6, len(observations))
    check("every subject carries its expected route and a score in range",
          all(o.get("expected_route") and o.get("score") is not None
              and 0.0 <= o["score"] <= 1.0 for o in observations))
    check("the seeded cases carry the scores the story depends on",
          abs(subjects.get("case_1", {}).get("score", -1) - 0.05) < 1e-6
          and abs(subjects.get("case_3", {}).get("score", -1) - 0.87) < 1e-6,
          {k: v.get("score") for k, v in subjects.items()})

    case_rows = [p for p in (bt.get("current", {}).get("result") or {}).get("predictions", [])
                 if p.get("kind") == "case"]
    check("the shipped thresholds route the demo cases exactly as designed",
          len(case_rows) == 3 and all(p["agrees"] for p in case_rows),
          [(p["subject"], p["route"]) for p in case_rows])

    results = bt.get("results") or []
    check("the grid only offers pairs that could actually be configured",
          bool(results)
          and all(r["investigation_threshold"] > r["anomaly_threshold"] for r in results),
          len(results))
    check("every grid entry scores the same subjects, so the rows are comparable",
          all(r["subjects"] == len(observations) for r in results))
    check("the backtest names a pair to work from",
          bool(bt.get("best")) and bt["best"].get("accuracy") is not None)
    check("the backtest states that choosing is a judgement, not a calculation",
          "judgement" in (bt.get("note") or ""))

    strict = (client.get("/api/admin/threshold-backtest?anomaly=0.98&investigation=0.99")
              .get_json() or {})
    high_gate = next((r for r in strict.get("results", [])
                      if r["anomaly_threshold"] == 0.98), None)
    check("a near-impossible gate is shown to miss work the story depends on",
          bool(high_gate) and high_gate["accuracy"] < 1.0 and bool(high_gate["misrouted"]),
          high_gate)

    applied = client.post("/api/admin/threshold-backtest/apply", json={
        "anomaly_threshold": 0.30, "investigation_threshold": 0.60})
    applied_body = applied.get_json() or {}
    check("a chosen threshold pair can be applied with its evidence",
          applied.status_code == 200
          and applied_body.get("settings", {}).get("anomaly_threshold") == 0.30,
          applied.status_code)
    check("the application records how many subjects it was checked against",
          applied_body.get("backtest", {}).get("subjects") == len(observations),
          applied_body.get("backtest"))

    analyst_token = (raw.post("/api/auth/login",
                              json={"username": "analyst", "password": "analyst123"})
                      .get_json() or {}).get("token")
    check("a threshold change is refused to anyone who cannot manage settings",
          raw.get("/api/admin/threshold-backtest",
                  headers={"Authorization": f"Bearer {analyst_token}"}).status_code == 403)
    check("an anonymous caller cannot run a backtest",
          raw.get("/api/admin/threshold-backtest").status_code == 401)

    nonsense = client.post("/api/admin/threshold-backtest/apply", json={
        "anomaly_threshold": 0.90, "investigation_threshold": 0.40})
    check("an investigation gate below the anomaly gate is refused outright",
          nonsense.status_code == 400, nonsense.status_code)

    restored = client.post("/api/admin/threshold-backtest/apply", json={
        "anomaly_threshold": 0.35, "investigation_threshold": 0.65})
    check("the demo thresholds can be restored",
          restored.status_code == 200
          and (restored.get_json() or {}).get("settings", {}).get("anomaly_threshold") == 0.35)

    # ── Graph depth ──────────────────────────────────────────────
    # How far the walk runs decides which accounts end up in a case, so widening it is
    # a scope decision: bounded, admin-set, and reported back with the evidence.
    print("\n── Graph depth ─────────────────────────────────────────────")

    one = client.get("/api/graph/expansion?case_id=case_2&max_hops=1").get_json() or {}
    two = client.get("/api/graph/expansion?case_id=case_2&max_hops=2").get_json() or {}
    check("a shallower walk reaches no more than a deeper one",
          set(one.get("added_entity_ids", [])) <= set(two.get("added_entity_ids", [])),
          (one.get("added_entity_ids"), two.get("added_entity_ids")))
    check("the walk reports the depth that was asked for",
          one.get("requested_max_hops") == 1 and two.get("requested_max_hops") == 2)
    check("the walk reports how far the recorded evidence actually reaches",
          one.get("hops", 0) <= one.get("requested_max_hops", 0))
    check("a deeper walk reaches at least as far as a shallow one",
          two.get("hops", 0) >= one.get("hops", 0))
    check("every entity reached names the link that put it there",
          all(link.get("from") and link.get("to") and link.get("via")
              for link in one.get("links", [])), one.get("links"))
    check("the response states the bounds depth is judged against",
          one.get("max_allowed_hops") == 5 and one.get("default_max_hops") >= 1,
          (one.get("max_allowed_hops"), one.get("default_max_hops")))

    check("an absurd depth request is capped rather than honoured",
          (client.get("/api/graph/expansion?case_id=case_2&max_hops=99").get_json() or {})
          .get("requested_max_hops") == 5)
    check("a depth of zero is floored to one hop",
          (client.get("/api/graph/expansion?case_id=case_2&max_hops=0").get_json() or {})
          .get("requested_max_hops") == 1)
    check("a depth that is not a number falls back to the default",
          (client.get("/api/graph/expansion?case_id=case_2&max_hops=soon").get_json() or {})
          .get("requested_max_hops") in (1, 2, 3, 4, 5))
    check("an anonymous caller cannot explore a network",
          raw.get("/api/graph/expansion?case_id=case_2").status_code == 401)
    check("a missing case is refused",
          client.get("/api/graph/expansion?case_id=case_nope").status_code == 404)

    wide = client.post("/api/pipeline/run/case_2", json={"max_hops": 4}).get_json() or {}
    stage_five = next((s for s in (wide.get("trace") or [])
                       if s.get("key") == "banks_identified"), {})
    check("a run honours the depth it was asked for",
          stage_five.get("detail", {}).get("max_hops") == 4,
          stage_five.get("detail", {}).get("max_hops"))
    check("a run never walks further than it was asked to",
          stage_five.get("detail", {}).get("hops", 0) <= 4)
    stored = (client.get("/api/cases/case_2").get_json() or {}).get("network_expansion") or {}
    check("the depth used is recorded on the case for later review",
          stored.get("max_hops") == 4, stored.get("max_hops"))

    clamped = client.post("/api/pipeline/run/case_2", json={"max_hops": 999}).get_json() or {}
    clamped_stage = next((s for s in (clamped.get("trace") or [])
                          if s.get("key") == "banks_identified"), {})
    check("a requested depth beyond the cap is clamped on a real run too",
          clamped_stage.get("detail", {}).get("max_hops") == 5,
          clamped_stage.get("detail", {}).get("max_hops"))

    print("\nDRAFTED REPORT —", coord_case["id"])
    print("=" * 78)
    report = run["report"]
    print(f"{report['recommendation']} — activity score {report['score'] * 100:.0f}%")
    confidence = report["confidence"]
    print(f"confidence: overall {confidence['overall']} "
          f"(pattern {confidence['pattern']}, intent {confidence['intent']})")
    for section in report["sections"]:
        print(f"\n## {section['title']}")
        for para in section.get("body", []):
            print("   " + para)
        bullets = section.get("bullets", [])
        for bullet in bullets[:4]:
            print("   - " + bullet)
        if len(bullets) > 4:
            print(f"   … {len(bullets) - 4} more")
    print(f"\n{report['disclaimer']}")
    print("=" * 78)

    print("\nAll pipeline checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
