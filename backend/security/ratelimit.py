"""
Context Guard — L3 · Request Throttling

Closes G-07, and closes a denial of service that the existing lockout created.

The problem being solved
-----------------------
`services/users.py` locks an account after 5 failed sign-ins. That is good against
one attacker guessing one password. It is also a weapon: a script that knows a
username (they are in the audit trail, in case ownership, in email) can send five
wrong passwords and lock a working analyst out of the platform, repeatedly, from
anywhere. Availability was attackable with `for` loop.

The fix is layered, not a replacement:

    per-IP        stops one host flooding the service at all
    per-account   counts failures *before* they reach the lockout, and answers 429
                  instead of continuing to burn the victim's five attempts
    per-write     state changes are cheaper to abuse than reads, so they get a
                  tighter budget than the general one
    lockout       still there, as the last line for a slow, distributed attempt

Honest limitations (stated rather than hidden)
---------------------------------------------
* Buckets live in this process's memory. Behind multiple workers each holds its
  own budget, so the effective limit multiplies by the worker count. A single
  process — which is how this application runs — is exact. Multi-worker
  deployments need a shared store (Redis) for the same guarantee; the interface
  here is deliberately the one a shared store would implement.
* `X-Forwarded-For` is only believed when `TRUST_PROXY_HEADERS=true`. Otherwise a
  caller could mint a new identity per request and never meet a limit.
* The clock is monotonic and local. It decides rate, never evidence, so it does not
  need to be trusted the way the audit timestamp does.
"""

import threading
import time

from flask import jsonify, request

from . import policy

# ── Bucket store ─────────────────────────────────────────────────────────────


class SlidingWindow:
    """A sliding-window counter, one list of timestamps per key.

    A sliding window is used rather than a fixed window so a burst cannot be split
    across two windows to double the allowance — the classic way a fixed-window
    limiter is defeated.
    """

    def __init__(self):
        self._hits = {}
        self._lock = threading.Lock()
        self._since_prune = 0

    def check(self, key, limit, window):
        """Consume one unit for `key`. Returns (allowed, retry_after_seconds, remaining)."""
        now = time.monotonic()
        with self._lock:
            hits = [t for t in self._hits.get(key, ()) if now - t < window]
            if len(hits) >= limit:
                self._hits[key] = hits
                retry = max(1, int(window - (now - hits[0])) + 1)
                return False, retry, 0
            hits.append(now)
            self._hits[key] = hits
            self._since_prune += 1
            if self._since_prune >= 500:
                self._prune(now)
                self._since_prune = 0
            return True, 0, limit - len(hits)

    def peek(self, key, window):
        """How many hits are currently counted for a key. Used by tests."""
        now = time.monotonic()
        with self._lock:
            return len([t for t in self._hits.get(key, ()) if now - t < window])

    def forget(self, key=None):
        """Drop one key, or all of them. Used by tests and by the fixture reset."""
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)

    def _prune(self, now):
        """Drop keys whose newest hit has aged out, so the dict cannot grow forever."""
        longest = max(policy.RATE_LIMIT_AUTH_ACCOUNT[1], policy.RATE_LIMIT_GENERAL[1],
                      policy.RATE_LIMIT_WRITE[1])
        for key in [k for k, v in self._hits.items() if not v or now - v[-1] > longest]:
            self._hits.pop(key, None)


LIMITER = SlidingWindow()

AUTH_PATHS = ("/api/auth/login",)


# ── Identity of the caller ───────────────────────────────────────────────────


def client_address():
    """The address a budget is charged to.

    A proxy header is honoured only when the deployment declares that it sits
    behind a proxy it controls. Believing it unconditionally would let any caller
    choose its own identity and never meet a limit.
    """
    if policy.TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _attempted_username():
    """The username a sign-in attempt names, for the per-account budget.

    Flask caches the parsed body, so reading it here does not consume it — the
    handler still receives the same decoded object.
    """
    if not request.is_json:
        return None
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return None
    username = body.get("username")
    return username.strip().lower() if isinstance(username, str) and username.strip() else None


# ── Enforcement ──────────────────────────────────────────────────────────────


def _too_many(message, retry_after, limit):
    response = jsonify({"error": message, "code": "rate_limited"})
    response.status_code = 429
    response.headers["Retry-After"] = str(retry_after)
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = "0"
    return response


def apply(app):
    @app.before_request
    def _throttle():
        path = request.path
        if not path.startswith("/api/"):
            return None

        address = client_address()

        # 1. Sign-in gets its own, tighter budget per client address.
        if path in AUTH_PATHS:
            allowed, retry, remaining = LIMITER.check(
                f"auth:{address}", *policy.RATE_LIMIT_AUTH)
            if not allowed:
                return _too_many(
                    "Too many sign-in attempts from this address. Please wait and try again.",
                    retry, policy.RATE_LIMIT_AUTH[0])

            # 2. And per named account, so one attacker cannot spend a real
            #    analyst's five attempts and lock them out. This budget is spent
            #    before authentication is even attempted.
            username = _attempted_username()
            if username:
                allowed, retry, _ = LIMITER.check(
                    f"acct:{username}", *policy.RATE_LIMIT_AUTH_ACCOUNT)
                if not allowed:
                    return _too_many(
                        "Too many attempts against this account. Please wait and try again.",
                        retry, policy.RATE_LIMIT_AUTH_ACCOUNT[0])
            return None

        # 3. State changes are held to a tighter budget than reads.
        if request.method in policy.WRITE_METHODS:
            allowed, retry, remaining = LIMITER.check(
                f"write:{address}", *policy.RATE_LIMIT_WRITE)
        else:
            # 4. Everything else: a generous ceiling that only a flood meets. It
            #    is deliberately far above what browsing the console costs, so
            #    ordinary use never sees it.
            allowed, retry, remaining = LIMITER.check(
                f"api:{address}", *policy.RATE_LIMIT_GENERAL)

        if not allowed:
            return _too_many(
                "Too many requests. Please slow down and try again.", retry,
                policy.RATE_LIMIT_WRITE[0] if request.method in policy.WRITE_METHODS
                else policy.RATE_LIMIT_GENERAL[0])
        return None

    @app.after_request
    def _advertise(response):
        """Tell a well-behaved client what its budget is, so it can back off first."""
        if request.path.startswith("/api/") and "X-RateLimit-Limit" not in response.headers:
            limit = (policy.RATE_LIMIT_AUTH[0] if request.path in AUTH_PATHS
                     else policy.RATE_LIMIT_WRITE[0] if request.method in policy.WRITE_METHODS
                     else policy.RATE_LIMIT_GENERAL[0])
            response.headers["X-RateLimit-Limit"] = str(limit)
        return response
