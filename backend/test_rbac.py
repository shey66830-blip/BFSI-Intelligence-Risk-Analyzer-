"""
Context Guard — RBAC verification suite

Exercises the four synthetic roles against the real Flask app + MongoDB, asserting
that each one can do its job and nothing more.

    cd backend && python test_rbac.py
"""

import sys

from app import create_app, init_database
from services.reset import reset_demo_state

PASSED = []
FAILED = []


def check(label, condition, detail=""):
    if condition:
        PASSED.append(label)
        print(f"  PASS  {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL  {label}  {detail}")


# Re-seeding before every run keeps it deterministic: without it, repeated runs
# accumulate transactions and accounts and shift the behavioural baseline.
reset_to_known_state = reset_demo_state


def main():
    print("── Bootstrapping ─────────────────────────────────────────────")
    reset_to_known_state()
    init_database()
    app = create_app()
    c = app.test_client()

    def login(username, password):
        r = c.post("/api/auth/login", json={"username": username, "password": password})
        body = r.get_json() or {}
        return r.status_code, body.get("token"), body.get("user") or {}

    def hdr(token):
        return {"Authorization": f"Bearer {token}"}

    print("\n── Authentication ────────────────────────────────────────────")
    status, _, _ = login("analyst", "wrong-password")
    check("wrong password is rejected", status == 401)

    status, _, _ = login("ghost", "analyst123")
    check("unknown username is rejected", status == 401)

    tokens = {}
    users = {}
    for username, password in [("analyst", "analyst123"), ("analyst2", "analyst123"),
                               ("compliance", "compliance123"), ("admin", "admin123")]:
        status, token, user = login(username, password)
        tokens[username] = token
        users[username] = user
        check(f"{username} signs in", status == 200 and token is not None)

    check("unauthenticated request is refused", c.get("/api/cases").status_code == 401)
    check("unauthenticated pipeline run is refused",
          c.post("/api/pipeline/run/case_1").status_code == 401)

    status, _, _ = login("analyst", "analyst123")
    r = c.post("/api/auth/logout", headers=hdr(tokens["analyst"]))
    check("logout succeeds", r.status_code == 200)
    check("revoked token stops working",
          c.get("/api/cases", headers=hdr(tokens["analyst"])).status_code == 401)
    tokens["analyst"] = login("analyst", "analyst123")[1]

    print("\n── Analyst: assigned cases only ──────────────────────────────")
    r = c.get("/api/cases", headers=hdr(tokens["analyst"]))
    ids = {x["id"] for x in r.get_json()}
    check("analyst sees own cases", ids == {"case_1", "case_2"}, str(ids))
    check("analyst's dashboard counts only their scope",
          (c.get("/api/dashboard-stats", headers=hdr(tokens["analyst"])).get_json() or {}).get("scope") == "assigned")
    check("analyst cannot see another analyst's case",
          c.get("/api/cases/case_3", headers=hdr(tokens["analyst"])).status_code == 403)
    check("analyst can open an assigned case",
          c.get("/api/cases/case_2", headers=hdr(tokens["analyst"])).status_code == 200)

    case2 = c.get("/api/cases/case_2", headers=hdr(tokens["analyst"])).get_json()
    names = [t["entity_name"] for t in case2["transactions"]]
    check("analyst identity is masked server-side",
          all("*" not in n and (n == "Unknown" or "." in n) for n in names), str(names[:3]))
    check("response declares masking level", case2["privacy"]["level"] == "masked")
    check("redacted fields are disclosed", "entity_name" in case2["privacy"]["redacted_fields"])
    description = case2.get("description", "")
    check("prose fields are scrubbed too, not just columns",
          "Rajesh Kumar" not in description and "R. Kumar" in description, description)
    check("transaction descriptions are scrubbed",
          not any("Rajesh Kumar" in t.get("description", "") for t in case2["transactions"]))

    print("\n── Analyst: permitted and forbidden actions ──────────────────")
    r = c.post("/api/pipeline/run/case_2", headers=hdr(tokens["analyst"]))
    check("analyst can run the pipeline on an assigned case", r.status_code == 200, r.status_code)
    check("analyst cannot run the pipeline on an unassigned case",
          c.post("/api/pipeline/run/case_3", headers=hdr(tokens["analyst"])).status_code == 403)

    r = c.post("/api/cases/case_2/decision",
               headers=hdr(tokens["analyst"]),
               json={"decision": "escalate_compliance", "rationale": "Trying to escalate"})
    check("analyst cannot escalate to compliance", r.status_code == 403, r.status_code)

    r = c.post("/api/cases/case_2/decision",
               headers=hdr(tokens["analyst"]),
               json={"decision": "close_explained", "rationale": "Hospital context and insurance claim confirm legitimacy"})
    body = r.get_json() or {}
    check("analyst can close a case with context", r.status_code == 200, r.status_code)
    check("decision is attributed to the session identity",
          (body.get("decision") or {}).get("investigator") == users["analyst"]["name"])

    check("analyst cannot list accounts",
          c.get("/api/users", headers=hdr(tokens["analyst"])).status_code == 403)
    check("analyst cannot write settings",
          c.put("/api/settings", headers=hdr(tokens["analyst"]), json={"anomaly_threshold": 0.1}).status_code == 403)
    check("analyst cannot see the org-wide audit trail",
          (c.get("/api/audit-logs?scope=all", headers=hdr(tokens["analyst"])).get_json() or {}).get("scope") == "own")

    print("\n── Compliance: review, escalate, unmasked ────────────────────")
    r = c.get("/api/cases", headers=hdr(tokens["compliance"]))
    ids = {x["id"] for x in r.get_json()}
    check("compliance sees every case", {"case_1", "case_2", "case_3"} <= ids, str(ids))
    check("compliance is not blocked on an unassigned case",
          c.get("/api/cases/case_3", headers=hdr(tokens["compliance"])).status_code == 200)

    case2_full = c.get("/api/cases/case_2", headers=hdr(tokens["compliance"])).get_json()
    check("compliance still reads the real name in prose",
          "Rajesh Kumar" in case2_full.get("description", ""), case2_full.get("description", ""))

    case3 = c.get("/api/cases/case_3", headers=hdr(tokens["compliance"])).get_json()
    unmasked = [t["entity_name"] for t in case3["transactions"]]
    check("compliance sees unmasked identifiers", case3["privacy"]["level"] == "full", str(unmasked[:2]))
    check("compliance sees a real customer name",
          any("GlobalTrade" in n or "Sharma" in n or "Vikram" in n for n in unmasked), str(unmasked[:3]))

    # Stage 12 rests on the stage-10 report: a case that has never been through the pipeline
    # has nothing to decide on, so the decision is refused until an investigation exists.
    r = c.post("/api/cases/case_3/decision",
               headers=hdr(tokens["compliance"]),
               json={"decision": "escalate_compliance", "rationale": "Escalating before any report"})
    check("a decision is refused while the case has no report", r.status_code == 409, r.status_code)
    check("the refusal names the missing report",
          (r.get_json() or {}).get("code") == "report_required", (r.get_json() or {}).get("code"))

    r = c.post("/api/pipeline/run/case_3", headers=hdr(tokens["compliance"]))
    check("compliance can run the pipeline on any case", r.status_code == 200, r.status_code)
    check("the run leaves a report the decision can rest on",
          bool((c.get("/api/cases/case_3", headers=hdr(tokens["compliance"])).get_json()
                or {}).get("pipeline_report")))

    r = c.post("/api/cases/case_3/decision",
               headers=hdr(tokens["compliance"]),
               json={"decision": "escalate_compliance",
                     "rationale": "Corroborated cross-bank layering; referring to the FIU"})
    check("compliance can escalate to the FIU", r.status_code == 200, r.status_code)
    check("escalation moves the case status",
          (c.get("/api/cases/case_3", headers=hdr(tokens["compliance"])).get_json() or {}).get("status") == "escalated")

    check("a decision without a rationale is rejected",
          c.post("/api/cases/case_3/decision", headers=hdr(tokens["compliance"]),
                 json={"decision": "continue_investigation", "rationale": ""}).status_code == 400)
    check("compliance cannot manage users",
          c.get("/api/users", headers=hdr(tokens["compliance"])).status_code == 403)

    r = c.get("/api/audit-logs", headers=hdr(tokens["compliance"]))
    check("compliance sees the organisation-wide trail",
          (r.get_json() or {}).get("scope") == "all")

    print("\n── Admin: users, assignments, settings ───────────────────────")
    r = c.get("/api/users", headers=hdr(tokens["admin"]))
    body = r.get_json() or {}
    check("admin lists accounts", r.status_code == 200 and len(body.get("users", [])) >= 4)
    check("admin receives the role catalogue", len(body.get("roles", [])) == 3)

    r = c.post("/api/users", headers=hdr(tokens["admin"]),
               json={"username": "temp_analyst", "password": "temp-pass-123", "name": "Temp Analyst",
                     "role": "analyst", "email": "temp@demo-bank.in"})
    body = r.get_json() or {}
    new_id = (body.get("user") or {}).get("id")
    check("admin creates an account", r.status_code == 201, r.status_code)
    check("new account hashes its password",
          "password" not in str(body.get("user")) and "password_hash" not in str(body.get("user")))

    r = c.post("/api/auth/login", json={"username": "temp_analyst", "password": "temp-pass-123"})
    check("the new account can sign in", r.status_code == 200)
    new_token = (r.get_json() or {}).get("token")
    check("a brand-new analyst owns no cases",
          c.get("/api/cases", headers=hdr(new_token)).get_json() == [])
    check("a brand-new analyst cannot see case_1",
          c.get("/api/cases/case_1", headers=hdr(new_token)).status_code == 403)

    r = c.patch(f"/api/users/{new_id}", headers=hdr(tokens["admin"]),
                json={"assigned_case_ids": ["case_1"]})
    check("admin assigns a case", r.status_code == 200, r.status_code)
    check("assignment is immediately effective",
          c.get("/api/cases/case_1", headers=hdr(new_token)).status_code == 200)

    r = c.patch(f"/api/users/{new_id}", headers=hdr(tokens["admin"]), json={"role": "compliance"})
    check("admin changes a role", r.status_code == 200)
    status, promoted, _ = login("temp_analyst", "temp-pass-123")
    check("promotion grants the wider scope",
          c.get("/api/cases/case_3", headers=hdr(promoted)).status_code == 200)
    check("role change revokes old sessions",
          c.get("/api/cases", headers=hdr(new_token)).status_code == 401)

    r = c.patch(f"/api/users/{new_id}", headers=hdr(tokens["admin"]), json={"status": "suspended"})
    check("admin suspends an account", r.status_code == 200)
    check("suspended account cannot sign in",
          login("temp_analyst", "temp-pass-123")[0] == 401)
    check("admin cannot suspend itself",
          c.patch(f"/api/users/{users['admin']['id']}", headers=hdr(tokens["admin"]),
                  json={"status": "suspended"}).status_code == 400)

    settings = c.get("/api/settings", headers=hdr(tokens["admin"])).get_json()
    check("admin reads settings", settings.get("anomaly_threshold") is not None)
    check("settings declare edit rights", settings.get("can_edit") is True)

    r = c.put("/api/settings", headers=hdr(tokens["admin"]),
              json={"anomaly_threshold": 0.9, "investigation_threshold": 0.5})
    check("invalid threshold ordering is rejected", r.status_code == 400, r.status_code)
    r = c.put("/api/settings", headers=hdr(tokens["admin"]), json={"anomaly_threshold": 0.3})
    check("admin updates the anomaly gate", r.status_code == 200, r.status_code)

    print("\n── Settings actually change behaviour ───────────────────────")
    r = c.put("/api/settings", headers=hdr(tokens["admin"]),
              json={"anomaly_threshold": 0.98, "investigation_threshold": 0.99,
                    "mask_analyst_pii": False})
    check("gate raised and masking disabled", r.status_code == 200)
    settings = r.get_json()

    case2 = c.get("/api/cases/case_2", headers=hdr(tokens["analyst"])).get_json()
    check("masking policy toggle unmasks analysts", case2["privacy"]["level"] == "full")

    r = c.post("/api/pipeline/ingest", headers=hdr(tokens["analyst"]), json={"scenario": "routine"})
    body = r.get_json() or {}
    check("a very high gate sends routine activity to no action",
          body.get("route") == "no_action", body.get("route"))
    check("no case is created when the gate is closed", body.get("case_created") is False)

    c.put("/api/settings", headers=hdr(tokens["admin"]),
          json={"anomaly_threshold": 0.35, "investigation_threshold": 0.65, "mask_analyst_pii": True})

    print("\n── Hospital demo end-to-end under RBAC ───────────────────────")
    r = c.post("/api/pipeline/ingest", headers=hdr(tokens["analyst"]), json={"scenario": "high_value"})
    body = r.get_json() or {}
    check("hospital payment routes to context verification",
          body.get("route") == "context_verification", body.get("route"))
    check("a case is created for the hospital payment", body.get("case_created") is True)
    live_case = (body.get("case") or {}).get("id")
    check("the live case is assigned to the acting analyst",
          (body.get("case") or {}).get("assigned_to") == users["analyst"]["id"])
    check("the analyst can open their new case",
          c.get(f"/api/cases/{live_case}", headers=hdr(tokens["analyst"])).status_code == 200)

    r = c.post(f"/api/pipeline/run/{live_case}", headers=hdr(tokens["analyst"]))
    trace = (r.get_json() or {}).get("trace") or []
    check("the 12-stage pipeline runs to completion", r.status_code == 200 and len(trace) == 12)
    check("hospital context appears in the report",
          any("Context Returned by Bank" == s.get("title")
              for s in ((r.get_json() or {}).get("report") or {}).get("sections", [])))
    check("stage 12 waits for a human", trace[-1]["status"] == "pending")

    r = c.post(f"/api/cases/{live_case}/decision", headers=hdr(tokens["analyst"]),
               json={"decision": "close_explained",
                     "rationale": "Insurance claim and hospital context explain the payment"})
    check("analyst records the hospital decision", r.status_code == 200, r.status_code)
    check("case closes on a documented explanation",
          (c.get(f"/api/cases/{live_case}", headers=hdr(tokens["analyst"])).get_json() or {}).get("status") == "closed")

    print("\n── Cross-bank scenario still works ───────────────────────────")
    r = c.post("/api/pipeline/ingest", headers=hdr(tokens["compliance"]), json={"scenario": "coordinated"})
    body = r.get_json() or {}
    check("coordinated scenario routes to investigation",
          body.get("route") == "investigation", body.get("route"))

    r = c.get("/api/graph/entity", headers=hdr(tokens["analyst"]))
    graph = r.get_json() or {}
    check("analyst graph is scoped to their cases", graph.get("scope") == "assigned")
    r = c.get("/api/graph/entity", headers=hdr(tokens["compliance"]))
    check("compliance graph covers the network", (r.get_json() or {}).get("scope") == "all")

    print("\n── Audit trail ───────────────────────────────────────────────")
    r = c.get("/api/audit-logs", headers=hdr(tokens["admin"]))
    entries = (r.get_json() or {}).get("entries", [])
    actions = {e["action"] for e in entries}
    check("audit trail records sign-ins", "login" in actions, str(sorted(actions)))
    check("audit trail records decisions", "decision" in actions)
    check("audit trail records denied access", "access_denied" in actions)
    check("audit entries carry the acting identity",
          all(e.get("user") for e in entries if e["action"] != "system"))

    own = c.get("/api/audit-logs", headers=hdr(tokens["analyst"])).get_json() or {}
    check("analyst trail contains only their own entries",
          all(e["username"] == "analyst" for e in own.get("entries", []) if e["action"] != "system"))

    print("\n" + "═" * 62)
    print(f"  {len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("  Failures:")
        for f in FAILED:
            print(f"    - {f}")
    print("═" * 62)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
