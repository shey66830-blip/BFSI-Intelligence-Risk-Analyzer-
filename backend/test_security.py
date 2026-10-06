"""
Context Guard — Security Invariants Suite

Asserts the guarantees the platform claims about itself, against the real Flask app
and MongoDB, so a regression fails the build instead of quietly weakening a control.

    cd backend && python test_security.py

Every check here is an invariant that must hold in any deployment. The gaps this
suite does NOT assert — because they are known and tracked, not yet true — are
listed in SECURITY.md under "Gap register". Read the two together: this file is the
floor that may not drop, that file is the road to production.

    credentials are stored, never echoed
    sessions are opaque, hashed at rest, and expire
    authority comes from the permission matrix, never from the request
    analysts never receive an identifier their role is not entitled to
    the audit trail is append-only over the API and names the actor
"""

import hashlib
import json
import secrets
import sys
from datetime import datetime, timedelta

from app import create_app, init_database
from config import get_db
from services import audit
from services.reset import reset_demo_state
from services.users import (
    AUTHORISATION_GATED,
    MAX_FAILED_ATTEMPTS,
    ROLE_PERMISSIONS,
    hash_token,
    has_permission,
    permissions_for,
)

PASSED, FAILED = [], []


def check(label, condition, detail=""):
    if condition:
        PASSED.append(label)
        print(f"  PASS  {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL  {label}  {detail}")


def body(response):
    return response.get_json() or {}


# A password that is never a demo credential, for the throwaway lifecycle checks.
PROBE_PASSWORD = "Probe-Pass-9f3a"


def main():
    print("── Bootstrapping ─────────────────────────────────────────────")
    reset_demo_state()
    init_database()
    db = get_db()
    # Restricted reads are gated on an authorisation, so the suite starts from a
    # clean access model rather than whatever a previous run left behind.
    db.access_requests.delete_many({"case_id": "case_2"})
    db.access_authorizations.delete_many({"case_id": "case_2"})

    app = create_app()
    c = app.test_client()

    def login(identifier, password):
        r = c.post("/api/auth/login", json={"username": identifier, "password": password})
        payload = body(r)
        return r.status_code, payload.get("token"), payload.get("user") or {}

    def hdr(token):
        return {"Authorization": f"Bearer {token}"}

    tokens = {}
    users = {}
    for username, password in [("analyst", "analyst123"), ("compliance", "compliance123"),
                               ("admin", "admin123")]:
        status, token, user = login(username, password)
        tokens[username] = token
        users[username] = user

    # ── Credential storage ────────────────────────────────────────
    print("\n── Credential storage ───────────────────────────────────────")

    analyst_doc = db.users.find_one({"username": "analyst"})
    stored = analyst_doc.get("password_hash") or ""
    check("a password is stored as a hash, not as the password",
          stored and stored != "analyst123" and "analyst123" not in stored, stored[:16])
    check("the stored hash uses a real password scheme, not a bare digest",
          ":" in stored and len(stored) > 40, stored[:24])
    check("no user document stores a plaintext password field",
          db.users.count_documents({"password": {"$exists": True}}) == 0)

    login_payload = body(c.post("/api/auth/login", json={
        "username": "analyst", "password": "analyst123"}))
    check("the login response carries no password material",
          "password" not in (login_payload.get("user") or {})
          and "password_hash" not in (login_payload.get("user") or {}))
    check("the signed-in identity carries no password material",
          "password_hash" not in body(c.get("/api/auth/me", headers=hdr(tokens["analyst"])))
                                 .get("user", {}))
    check("a failed attempt counter is not exposed to the client",
          "failed_attempts" not in (login_payload.get("user") or {}))

    roster = body(c.get("/api/users", headers=hdr(tokens["admin"]))).get("users", [])
    check("the user administration listing exposes no hash to anyone",
          roster and not any("password_hash" in u for u in roster), len(roster))

    # ── Session handling ──────────────────────────────────────────
    print("\n── Session handling ─────────────────────────────────────────")

    raw_token = tokens["analyst"]
    check("a session token has real entropy",
          isinstance(raw_token, str) and len(raw_token) >= 40, len(raw_token or ""))
    check("a session is stored under the hash of its token",
          db.sessions.find_one({"token_hash": hash_token(raw_token)}) is not None)
    check("the raw token is not stored anywhere in the sessions collection",
          db.sessions.count_documents({"$or": [{"token": raw_token},
                                               {"token_hash": raw_token}]}) == 0)
    check("the token hash is the deterministic digest of the token",
          hash_token(raw_token) == hashlib.sha256(raw_token.encode("utf-8")).hexdigest())
    check("a session records when it expires",
          bool((db.sessions.find_one({"token_hash": hash_token(raw_token)}) or {})
               .get("expires_at")))

    dead_token = "sec-" + secrets.token_hex(24)
    db.sessions.insert_one({
        "token_hash": hash_token(dead_token), "user_id": analyst_doc["id"],
        "issued_at": datetime.utcnow() - timedelta(hours=9),
        "expires_at": datetime.utcnow() - timedelta(hours=1),
    })
    check("an expired session is refused",
          c.get("/api/cases", headers=hdr(dead_token)).status_code == 401)
    db.sessions.delete_one({"token_hash": hash_token(dead_token)})

    check("a forged token is refused",
          c.get("/api/cases", headers=hdr("not-a-real-token")).status_code == 401)
    c.post("/api/auth/logout", headers=hdr(tokens["compliance"]))
    check("a signed-out session cannot be replayed",
          c.get("/api/cases", headers=hdr(tokens["compliance"])).status_code == 401)
    tokens["compliance"] = login("compliance", "compliance123")[1]

    # ── Authentication is required ────────────────────────────────
    print("\n── Authentication is required ───────────────────────────────")

    protected = [
        ("GET", "/api/cases"),
        ("GET", "/api/cases/case_1"),
        ("GET", "/api/notifications"),
        ("GET", "/api/audit-logs"),
        ("GET", "/api/locked-resources?case_id=case_2"),
        ("GET", "/api/access-requests"),
        ("GET", "/api/restricted/case_2"),
        ("GET", "/api/admin/system-status"),
        ("POST", "/api/cases/case_1/status"),
        ("POST", "/api/pipeline/run/case_1"),
    ]
    open_routes = []
    for method, path in protected:
        response = c.open(path, method=method, json={})
        if response.status_code != 401:
            open_routes.append(f"{method} {path} -> {response.status_code}")
    check("every protected route refuses an anonymous caller with a 401",
          not open_routes, open_routes)

    # ── Authorisation boundaries ──────────────────────────────────
    print("\n── Authorisation boundaries ─────────────────────────────────")

    escalations = [
        ("analyst", "GET", "/api/users"),
        ("analyst", "POST", "/api/users"),
        ("analyst", "PUT", "/api/settings"),
        ("analyst", "GET", "/api/admin/system-status"),
        ("analyst", "GET", "/api/admin/audit-logs"),
        ("compliance", "GET", "/api/users"),
        ("compliance", "PUT", "/api/settings"),
        ("compliance", "POST", "/api/users"),
    ]
    allowed = []
    for who, method, path in escalations:
        response = c.open(path, method=method, headers=hdr(tokens[who]),
                          json={"username": "x", "password": "y" * 8})
        if response.status_code != 403:
            allowed.append(f"{who} {method} {path} -> {response.status_code}")
    check("no role reaches a route outside its permission set",
          not allowed, allowed)

    check("an administrator cannot raise an access request (separation of duties)",
          c.post("/api/access-requests", headers=hdr(tokens["admin"]),
                 json={"case_id": "case_2", "categories": ["identity"],
                       "reason": "x", "necessity": "y"}).status_code == 403)
    check("an analyst cannot approve anyone's access request",
          c.post("/api/access-requests/REQ-NONE/approve", headers=hdr(tokens["analyst"]),
                 json={}).status_code in (403, 404))
    check("a compliance officer cannot approve an access request",
          c.post("/api/access-requests/REQ-NONE/approve", headers=hdr(tokens["compliance"]),
                 json={}).status_code == 403)

    # ── Permission matrix invariants ──────────────────────────────
    print("\n── Permission matrix ────────────────────────────────────────")

    every_role = set()
    for role, perms in ROLE_PERMISSIONS.items():
        every_role |= set(perms)
    check("a capability that needs an authorisation is in no role at all",
          "restricted:view" not in every_role)
    check("the approver role cannot raise what it approves",
          not has_permission("admin", "access:request"))
    check("an analyst holds no decision, user or policy authority",
          not any(has_permission("analyst", p)
                  for p in ("cases:decide", "users:manage", "settings:manage",
                            "access:approve", "audit:view_all")))
    check("a compliance officer holds no user or policy authority",
          not any(has_permission("compliance", p)
                  for p in ("users:manage", "settings:manage", "access:approve")))
    check("the administrator's set covers every other role, bar the duties withheld from it",
          (set(permissions_for("compliance")) | set(permissions_for("analyst")))
          - {"access:request"} <= set(permissions_for("admin")))
    check("every authorisation-gated capability is withheld from at least one role",
          AUTHORISATION_GATED and
          any(not has_permission(r, p) for r in ROLE_PERMISSIONS for p in AUTHORISATION_GATED))

    # ── Server-side masking ───────────────────────────────────────
    print("\n── Server-side masking ──────────────────────────────────────")

    raw_values = set()
    for txn in db.transactions.find({"case_id": "case_2"}):
        for field in ("entity_name", "counterparty", "account_number", "device_id"):
            value = txn.get(field)
            if value and str(value) != "Unknown" and len(str(value)) > 4:
                raw_values.add(str(value))

    masked_payload = json.dumps(body(c.get("/api/cases/case_2", headers=hdr(tokens["analyst"]))))
    leaked = sorted(v for v in raw_values if v in masked_payload)
    check("an analyst's case payload contains no raw identifier",
          not leaked, leaked[:5])

    other_case = body(c.get("/api/cases/case_2", headers=hdr(tokens["compliance"])))
    check("a compliance officer receives the unmasked view", 
          other_case.get("privacy", {}).get("level") == "full")

    restricted = body(c.get("/api/restricted/case_2", headers=hdr(tokens["analyst"])))
    check("restricted subject information is locked without an authorisation",
          restricted.get("locked") is True and not restricted.get("records"),
          restricted.get("state"))

    # ── Audit integrity ───────────────────────────────────────────
    print("\n── Audit integrity ──────────────────────────────────────────")

    c.get("/api/cases/case_3", headers=hdr(tokens["analyst"]))          # out of scope
    c.get("/api/restricted/case_2", headers=hdr(tokens["analyst"]))     # locked read

    analyst_id = analyst_doc["id"]
    denials = db.audit_log.find({"action": "access_denied", "user_id": analyst_id})
    check("a refused action is written to the trail with the actor who attempted it",
          any(e.get("result") == "denied" for e in denials))
    check("a refused restricted read is written to the trail",
          db.audit_log.count_documents({"action": "restricted_denied",
                                        "user_id": analyst_id}) >= 1)

    login("sec-trail-probe", "wrong-password")
    check("a failed sign-in is recorded as a system event, not attributed to a user",
          db.audit_log.count_documents({"action": "login_failed", "user_id": None}) >= 1)

    own_trail = body(c.get("/api/audit-logs", headers=hdr(tokens["analyst"]))).get("entries", [])
    check("an analyst's audit view is scoped to their own activity",
          own_trail and all(e.get("user_id") == analyst_id for e in own_trail),
          len(own_trail))
    check("the administrator's audit console shows activity from more than one identity",
          len({e.get("user_id") for e in
               body(c.get("/api/admin/audit-logs", headers=hdr(tokens["admin"])))
               .get("entries", [])}) > 1)

    check("the trail cannot be deleted over the API",
          c.delete("/api/audit-logs", headers=hdr(tokens["admin"])).status_code in (404, 405))
    check("the trail cannot be rewritten over the API",
          c.put("/api/audit-logs", headers=hdr(tokens["admin"]),
                json={}).status_code in (404, 405))
    check("no route can amend an individual audit entry",
          c.patch("/api/audit-logs/aud_0000000000", headers=hdr(tokens["admin"]),
                  json={}).status_code in (404, 405))

    # Append-only over the API is a convention. An edit made directly in the database —
    # the insider move the trail exists to catch — has to be detectable.
    print("\n── Audit chain ──────────────────────────────────────────────")

    integrity = c.get("/api/admin/audit-integrity", headers=hdr(tokens["admin"]))
    report = body(integrity)
    check("the chain verifies against a clean trail",
          integrity.status_code == 200 and report.get("ok") is True, report)
    check("verification reports how many entries it checked",
          report.get("entries", 0) > 0, report.get("entries"))
    check("the chain head agrees with the last entry",
          report.get("head_matches") is True, report.get("head_matches"))

    sample = db.audit_log.find_one({"entry_hash": {"$exists": True}}, sort=[("seq", -1)])
    check("every entry carries a sequence number, a hash and a link",
          bool(sample) and sample.get("seq") and sample.get("prev_hash")
          and sample.get("entry_hash"))
    seqs = [e["seq"] for e in db.audit_log.find({}, {"seq": 1}).sort("seq", 1)]
    check("sequence numbers are contiguous",
          bool(seqs) and seqs == list(range(seqs[0], seqs[0] + len(seqs))), seqs[:6])

    check("a compliance officer can verify the trail",
          c.get("/api/admin/audit-integrity",
                headers=hdr(tokens["compliance"])).status_code == 200)
    check("an analyst cannot verify the organisation-wide trail",
          c.get("/api/admin/audit-integrity",
                headers=hdr(tokens["analyst"])).status_code == 403)

    victim = db.audit_log.find_one({"action": "login"})
    check("there is an entry to tamper with", bool(victim))
    original_detail = victim.get("detail")
    db.audit_log.update_one({"id": victim["id"]},
                            {"$set": {"detail": "signed in as Someone Else"}})
    tampered = audit.verify(db)
    check("an entry edited directly in the database is detected",
          tampered["ok"] is False and tampered.get("break_seq") == victim["seq"], tampered)
    check("the break explains what stopped matching",
          "no longer matches" in (tampered.get("reason") or ""), tampered.get("reason"))
    check("the verification endpoint reports the break too",
          body(c.get("/api/admin/audit-integrity", headers=hdr(tokens["admin"])))
          .get("ok") is False)

    db.audit_log.update_one({"id": victim["id"]}, {"$set": {"detail": original_detail}})
    check("the trail verifies once the entry is restored",
          audit.verify(db)["ok"] is True)

    # A missing entry is a different kind of break: the sequence itself gives it away.
    gone = db.audit_log.find_one({"action": "login"})
    db.audit_log.delete_one({"_id": gone["_id"]})
    removed = audit.verify(db)
    check("a deleted entry breaks the sequence even if nothing else was touched",
          removed["ok"] is False and removed.get("break_seq") is not None, removed)
    db.audit_log.insert_one(gone)
    check("the trail verifies again once the entry is back",
          audit.verify(db)["ok"] is True)

    # ── Account lifecycle ─────────────────────────────────────────
    print("\n── Account lifecycle ───────────────────────────────────────")

    created = c.post("/api/users", headers=hdr(tokens["admin"]), json={
        "username": "sec_probe", "password": PROBE_PASSWORD,
        "role": "analyst", "name": "Security Probe"})
    probe = body(created).get("user") or {}
    check("an administrator can provision an account", created.status_code == 201 and probe)

    check("a short password is refused",
          c.post("/api/users", headers=hdr(tokens["admin"]), json={
              "username": "sec_short", "password": "short", "role": "analyst",
          }).status_code == 400)
    check("an unknown role is refused",
          c.post("/api/users", headers=hdr(tokens["admin"]), json={
              "username": "sec_role", "password": PROBE_PASSWORD, "role": "superuser",
          }).status_code == 400)

    _, probe_token, _ = login("sec_probe", PROBE_PASSWORD)
    check("the provisioned account can sign in", probe_token is not None)

    for _ in range(MAX_FAILED_ATTEMPTS):
        login("sec_probe", "definitely-wrong")
    check("repeated failures lock the account",
          (db.users.find_one({"username": "sec_probe"}) or {}).get("status") == "suspended")
    check("a locked account cannot sign in even with the right password",
          login("sec_probe", PROBE_PASSWORD)[0] == 401)

    c.patch(f"/api/users/{probe['id']}", headers=hdr(tokens["admin"]),
            json={"status": "active", "password": PROBE_PASSWORD})
    _, probe_token, _ = login("sec_probe", PROBE_PASSWORD)
    check("an administrator can reinstate it", probe_token is not None)

    c.patch(f"/api/users/{probe['id']}", headers=hdr(tokens["admin"]),
            json={"role": "compliance"})
    check("changing a role revokes that identity's existing sessions",
          c.get("/api/cases", headers=hdr(probe_token)).status_code == 401)

    # ── Enumeration and the demo surface ──────────────────────────
    print("\n── Enumeration & demo surface ───────────────────────────────")

    unknown = body(c.post("/api/auth/login", json={"username": "no-such-user",
                                                   "password": "whatever"}))
    wrong = body(c.post("/api/auth/login", json={"username": "analyst",
                                                 "password": "whatever"}))
    check("a wrong password and an unknown user are indistinguishable",
          unknown.get("error") == wrong.get("error"), (unknown.get("error"), wrong.get("error")))
    check("login failures do not confirm whether an account exists",
          "user" not in unknown and "user" not in wrong)

    db.settings.update_one({"id": "org_settings"}, {"$set": {"demo_mode": False}}, upsert=True)
    check("the synthetic accounts are withheld outside demo mode",
          c.get("/api/auth/demo-accounts").get_json() == [])
    db.settings.update_one({"id": "org_settings"}, {"$set": {"demo_mode": True}}, upsert=True)

    # ── Cleanup ───────────────────────────────────────────────────
    db.users.delete_many({"username": {"$in": ["sec_probe", "sec_short", "sec_role"]}})
    db.sessions.delete_many({})

    print("\n" + "═" * 62)
    print(f"  {len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("  Failures:")
        for failure in FAILED:
            print(f"    - {failure}")
    print("═" * 62)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
