"""
Context Guard — Security Controls Suite

Asserts the controls added in `backend/security/`. The companion suite,
`test_security.py`, guards what the platform already did (credentials, sessions,
authorisation, masking, the audit chain). This one guards the layer that was
missing: response hardening, origin trust, throttling, input validation, a boot
posture guard, and privacy classification.

    cd backend && python test_security_controls.py

Every check here proves a control *fires*. A control that is installed but never
blocks anything is not a control, so each one is asserted against a request that
must be refused, not merely against the presence of a header.
"""

import os
import sys

from app import create_app
from config import get_db
from security import classification, cors, logguard, policy, posture
from security.ratelimit import LIMITER

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


def main():
    print("── Bootstrapping ─────────────────────────────────────────────")
    app = create_app()
    c = app.test_client()
    # Budgets are per process, and this suite deliberately exhausts them.
    LIMITER.forget()

    # ═══════════════════════════════════════════════════════════════════════
    print("\n── L1 · Response hardening ───────────────────────────────────")

    r = c.get("/api/health")
    check("an API response carries the security header set",
          all(r.headers.get(name) == value for name, value in policy.BASE_HEADERS.items()),
          f"missing: {[n for n in policy.BASE_HEADERS if r.headers.get(n) != policy.BASE_HEADERS[n]]}")

    csp = r.headers.get("Content-Security-Policy", "")
    check("the API policy permits no script execution",
          "default-src 'none'" in csp and "script-src" not in csp, csp)
    check("the API policy refuses inline script",
          "unsafe-inline" not in csp and "unsafe-eval" not in csp, csp)
    check("the API cannot be framed", "frame-ancestors 'none'" in csp, csp)

    check("personal data is marked uncacheable",
          "no-store" in (r.headers.get("Cache-Control") or ""),
          r.headers.get("Cache-Control"))
    check("the originating stack is not advertised",
          r.headers.get("X-Powered-By") is None)

    # The header set must survive a response the app never intended — a 401 and a
    # route that does not exist are still responses an attacker learns from.
    r401 = c.get("/api/cases")
    check("headers are applied to refusals too", r401.status_code == 401
          and r401.headers.get("X-Content-Type-Options") == "nosniff")
    r404 = c.get("/api/does-not-exist")
    check("headers are applied to errors too",
          r404.headers.get("Content-Security-Policy") == policy.API_CSP)

    check("HSTS is asserted only where TLS is guaranteed",
          ("Strict-Transport-Security" in r.headers) == policy.IS_PRODUCTION)

    # ═══════════════════════════════════════════════════════════════════════
    print("\n── L2 · Origin trust ─────────────────────────────────────────")

    allowed = policy.ALLOWED_ORIGINS[0]
    r = c.get("/api/health", headers={"Origin": allowed})
    check("an allowlisted origin is answered",
          r.headers.get("Access-Control-Allow-Origin") == allowed,
          r.headers.get("Access-Control-Allow-Origin"))

    r = c.get("/api/health", headers={"Origin": "https://evil.example"})
    check("an unlisted origin is not granted access",
          r.headers.get("Access-Control-Allow-Origin") is None,
          r.headers.get("Access-Control-Allow-Origin"))

    check("the allowlist is never a wildcard", "*" not in policy.ALLOWED_ORIGINS)
    check("no response ever answers with a wildcard",
          c.get("/api/health", headers={"Origin": "https://evil.example"})
          .headers.get("Access-Control-Allow-Origin") != "*")
    check("denied() recognises an unlisted origin",
          cors.denied("https://evil.example"))
    check("denied() accepts a listed origin",
          not cors.denied(policy.ALLOWED_ORIGINS[0]))

    # ═══════════════════════════════════════════════════════════════════════
    print("\n── L3 · Input validation ─────────────────────────────────────")

    r = c.post("/api/cases", json={"username": {"$ne": None}})
    check("a MongoDB operator key is refused",
          r.status_code == 400 and body(r).get("code") == "invalid_request",
          f"{r.status_code} {body(r)}")

    r = c.post("/api/cases", json={"__proto__": {"isAdmin": True}})
    check("a prototype-pollution key is refused", r.status_code == 400,
          f"{r.status_code} {body(r)}")

    r = c.get("/api/cases?%24where=1")
    check("an operator key in the query string is refused", r.status_code == 400,
          r.status_code)

    deep = {"a": {}}
    node = deep["a"]
    for _ in range(policy.MAX_JSON_DEPTH + 3):
        node["a"] = {}
        node = node["a"]
    r = c.post("/api/cases", json=deep)
    check("a deeply nested payload is refused", r.status_code == 400,
          f"{r.status_code} {body(r)}")

    r = c.post("/api/cases", data=b'{"x":"' + b"a" * (policy.MAX_BODY_BYTES + 1024) + b'"}',
               content_type="application/json")
    check("an oversized body is refused with 413", r.status_code == 413,
          f"{r.status_code} {body(r)}")

    # A rejection that also rejects legitimate traffic is not a fix. This is the
    # control's own false-positive check.
    r = c.post("/api/auth/login", json={"username": "analyst", "password": "analyst123"})
    check("a legitimate sign-in is unaffected by the guard", r.status_code == 200,
          f"{r.status_code} {body(r)}")

    # ═══════════════════════════════════════════════════════════════════════
    print("\n── L3 · Throttling ───────────────────────────────────────────")

    LIMITER.forget()

    # Account budget: this is the control that stops an attacker spending a real
    # analyst's five lockout attempts. It must bite before the lockout does.
    probe = "ctrl_probe_account"
    limit = policy.RATE_LIMIT_AUTH_ACCOUNT[0]
    statuses = [c.post("/api/auth/login",
                       json={"username": probe, "password": "wrong-password"}).status_code
                for _ in range(limit)]
    check("attempts below the account budget are allowed",
          all(s == 401 for s in statuses), statuses)

    r = c.post("/api/auth/login", json={"username": probe, "password": "wrong-password"})
    check("the attempt past the account budget is refused with 429",
          r.status_code == 429, r.status_code)
    check("the refusal tells the client how long to wait",
          (r.headers.get("Retry-After") or "").isdigit(),
          r.headers.get("Retry-After"))
    check("the refusal carries a machine-readable reason",
          body(r).get("code") == "rate_limited", body(r))

    # Client-address budget: distinct usernames share one address, so the address
    # budget must still close even when no single account is attacked twice.
    LIMITER.forget()
    auth_limit = policy.RATE_LIMIT_AUTH[0]
    statuses = [c.post("/api/auth/login",
                       json={"username": f"ctrl_probe_ip_{index}", "password": "nope"}).status_code
                for index in range(auth_limit)]
    # Every attempt used a *different* username, so no account budget was reached.
    # They all still count against the one client address, which is the control
    # that makes per-account evasion pointless.
    check("spreading attempts across usernames does not evade the address budget",
          all(s == 401 for s in statuses),
          f"{auth_limit} attempts returned {sorted(set(statuses))}")
    check("each distinct username stayed under its own account budget",
          LIMITER.peek("acct:ctrl_probe_ip_0", 300) == 1,
          LIMITER.peek("acct:ctrl_probe_ip_0", 300))
    r = c.post("/api/auth/login", json={"username": "ctrl_probe_ip_final", "password": "nope"})
    check("the request past the address budget is refused", r.status_code == 429, r.status_code)

    # Sliding window: a fixed window can be defeated by splitting a burst across
    # the boundary. Assert the bucket counts within the window, not per calendar minute.
    LIMITER.forget()
    allowed_first = [LIMITER.check("ctrl:window", 3, 60)[0] for _ in range(3)]
    denied_next = LIMITER.check("ctrl:window", 3, 60)[0]
    check("the limiter counts a burst as one window",
          all(allowed_first) and not denied_next, (allowed_first, denied_next))
    check("hits are visible to the caller for backoff",
          LIMITER.peek("ctrl:window", 60) == 3, LIMITER.peek("ctrl:window", 60))

    # A rejected payload must not consume budget a legitimate request then waits on.
    LIMITER.forget()
    c.post("/api/cases", json={"$where": "1"})
    check("an invalid request does not consume the rate budget",
          LIMITER.peek(f"api:{c.environ_base.get('REMOTE_ADDR', 'unknown')}", 60) == 0
          or LIMITER.peek("api:127.0.0.1", 60) == 0,
          LIMITER.peek("api:127.0.0.1", 60))

    LIMITER.forget()

    # ═══════════════════════════════════════════════════════════════════════
    print("\n── L3 · Boot posture ─────────────────────────────────────────")

    original_env = os.environ.get("APP_ENVIRONMENT")
    original_origins = os.environ.get("ALLOWED_ORIGINS")
    original_debug = os.environ.get("FLASK_DEBUG")
    original_production = policy.IS_PRODUCTION
    try:
        check("a demonstration environment boots without complaint",
              posture._problems() == [], posture._problems())

        policy.IS_PRODUCTION = True
        os.environ["APP_ENVIRONMENT"] = "production"
        os.environ["FLASK_DEBUG"] = "true"
        os.environ["ALLOWED_ORIGINS"] = ""
        problems = posture._problems()
        check("debug mode is refused in production",
              any("FLASK_DEBUG" in p for p in problems), problems)
        check("an unnamed origin allowlist is refused in production",
              any("ALLOWED_ORIGINS" in p for p in problems), problems)
        check("an unauthenticated local database is refused in production",
              any("MONGO_URI" in p for p in problems), problems)
        check("the guard raises rather than warning",
              _raises(posture.assert_posture), "assert_posture returned normally")

        os.environ["FLASK_DEBUG"] = "false"
        os.environ["ALLOWED_ORIGINS"] = "https://console.example.in"
        problems = posture._problems()
        check("the guard clears once the configuration is fixed",
              not any("FLASK_DEBUG" in p or "ALLOWED_ORIGINS" in p for p in problems),
              problems)
    finally:
        policy.IS_PRODUCTION = original_production
        for key, value in (("APP_ENVIRONMENT", original_env),
                           ("ALLOWED_ORIGINS", original_origins),
                           ("FLASK_DEBUG", original_debug)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    # ═══════════════════════════════════════════════════════════════════════
    print("\n── L6 · Privacy classification ───────────────────────────────")

    check("the personal-data registry has not silently shrunk",
          classification.assert_registry_intact(list(policy.PII_FIELDS)))
    check("restricted fields are identified separately from personal ones",
          classification.restricted_fields() >= {"pan", "aadhaar"},
          classification.restricted_fields())
    check("every data class has a retention period",
          all(classification.retention_days(c) for c in policy.RETENTION_DAYS),
          policy.RETENTION_DAYS)
    check("the audit trail outlives what it describes",
          classification.retention_days("A0") > classification.retention_days("C3"))

    record = {"id": "case_2", "entity_name": "Rajesh Kumar",
              "account_number": "123456789012", "status": "context_verification"}
    described = classification.describe(record)
    check("a record can be described without reproducing its values",
          "Rajesh Kumar" not in str(described) and "123456789012" not in str(described),
          described)
    check("the description names which personal fields are present",
          set(described["personal_fields"]) == {"entity_name", "account_number"},
          described)

    # ═══════════════════════════════════════════════════════════════════════
    print("\n── L6 · Log scrubbing ────────────────────────────────────────")

    check("an email is redacted",
          "ananya.iyer@bank.in" not in logguard.scrub("email=ananya.iyer@bank.in"))
    check("an account number is redacted but stays correlated",
          logguard.scrub("acct=123456789012") == "acct=XXXX-9012",
          logguard.scrub("acct=123456789012"))
    check("a PAN is redacted", "ABCDE1234F" not in logguard.scrub("pan=ABCDE1234F"))
    check("a phone number is redacted", "9876543210" not in logguard.scrub("phone=9876543210"))
    check("a personal field is redacted by name even in free text",
          "Apollo Hospitals" not in logguard.scrub("entity_name='Apollo Hospitals'"),
          logguard.scrub("entity_name='Apollo Hospitals'"))
    check("loopback addresses survive so logs stay diagnostic",
          "127.0.0.1" in logguard.scrub("listening on 127.0.0.1"),
          logguard.scrub("listening on 127.0.0.1"))
    check("a real client address is masked",
          "203.0.113.44" not in logguard.scrub("request from 203.0.113.44"))

    # The control must work on a real log record, not only on a string.
    import logging
    record_log = logging.LogRecord("test", logging.WARNING, __file__, 1,
                                   "case opened for entity_name=%s",
                                   ("Rajesh Kumar",), None)
    logguard.ScrubFilter().filter(record_log)
    check("a log record is scrubbed through the filter path",
          "Rajesh Kumar" not in record_log.getMessage(), record_log.getMessage())
    check("a non-personal log line is left intact",
          "case_2" in logguard.scrub("loading case_2"),
          logguard.scrub("loading case_2"))

    # ═══════════════════════════════════════════════════════════════════════
    get_db().sessions.delete_many({})
    LIMITER.forget()

    print("\n" + "═" * 62)
    print(f"  {len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("  Failures:")
        for failure in FAILED:
            print(f"    - {failure}")
    print("═" * 62)
    return 1 if FAILED else 0


def _raises(fn):
    try:
        fn()
        return False
    except posture.InsecurePosture:
        return True


if __name__ == "__main__":
    sys.exit(main())
