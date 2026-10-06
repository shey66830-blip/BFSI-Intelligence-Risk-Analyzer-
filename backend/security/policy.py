"""
Context Guard — Security Policy

One place where every security decision is declared, so a control can never be
weakened by a route forgetting a rule, and so a reviewer has a single file to read.

Design rules:

* **Fail closed.** A missing or unparseable setting takes the safe value, never the
  permissive one. There is deliberately no "disable security" switch: to turn a
  control off you must edit this file, which is a reviewable act.
* **The environment scopes policy, it does not bypass it.** Development needs
  `unsafe-inline` for the Vite HMR preamble; production must not have it. That is
  the *correct* policy for each environment, not a way to switch protection off.
* **Everything is a value, not a branch.** Limits are constants so they can be
  asserted by tests rather than guessed at.
"""

import os

# ── Environment ──────────────────────────────────────────────────────────────

ENVIRONMENT = (os.environ.get("APP_ENVIRONMENT") or "Demonstration").strip()
IS_PRODUCTION = ENVIRONMENT.lower() in {"production", "prod", "live"}


def _origins_from_env():
    """Allowed browser origins, comma separated.

    The defaults are the local development console. Production MUST set
    `ALLOWED_ORIGINS`; `assert_posture()` refuses to boot otherwise, because the
    alternative is silently shipping an open API.
    """
    raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
    if not raw:
        return [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    return [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]


ALLOWED_ORIGINS = _origins_from_env()

# A browser sends no Origin header for same-origin and non-CORS requests, which is
# the normal path for this application (Vite proxies /api to Flask). Only requests
# that *claim* a cross-origin identity are checked.
REQUIRE_EXPLICIT_ORIGIN_IN_PRODUCTION = True

# ── L3 · Request throttling ──────────────────────────────────────────────────
#
# Two independent budgets. The per-IP budget stops one host flooding the service;
# the auth budget stops credential stuffing. The account budget is what stops an
# attacker using the *existing* lockout (5 wrong passwords) as a denial-of-service
# against a known analyst.

RATE_LIMIT_GENERAL = (300, 60)      # (requests, window seconds) — any /api route
RATE_LIMIT_AUTH = (20, 60)          # sign-in endpoint, per client address
RATE_LIMIT_AUTH_ACCOUNT = (10, 300) # failures attributable to one username
RATE_LIMIT_WRITE = (60, 60)         # state-changing methods, per client address

# Methods that change state, and therefore get the tighter budget.
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Client-address resolution. `X-Forwarded-For` is only believed when the app is
# behind a proxy we control, otherwise a caller could spoof the header and get a
# fresh budget per request.
TRUST_PROXY_HEADERS = os.environ.get("TRUST_PROXY_HEADERS", "").lower() == "true"

# ── L3 · Request validation ──────────────────────────────────────────────────

# No legitimate JSON body or query string in this application needs these keys.
# `$`-prefixed keys are MongoDB query operators; the others are prototype-pollution
# vectors. Rejecting them centrally means a new endpoint cannot forget to.
FORBIDDEN_KEY_PREFIXES = ("$",)
FORBIDDEN_KEYS = {"__proto__", "constructor", "prototype"}

MAX_BODY_BYTES = 1 * 1024 * 1024        # 1 MiB — a case payload is a few KiB
MAX_JSON_DEPTH = 12                     # stops a deeply-nested parse bomb
MAX_STRING_LENGTH = 200_000             # stops one enormous field

# ── L1 · Response headers ────────────────────────────────────────────────────
#
# The API answers with JSON, so its own policy can be maximally restrictive: this
# origin is never a document, never frames anything, and loads no sub-resources.

API_CSP = (
    "default-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "sandbox"
)

# Headers applied to every API response. The browser-side equivalent for the HTML
# is served by the static host — see security/web/security-headers.conf, because a
# document's policy has to travel with the document, not with a JSON API.
BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": API_CSP,
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-site",
    "Permissions-Policy": (
        "accelerometer=(), camera=(), display-capture=(), geolocation=(), "
        "gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()"
    ),
}

# Responses that carry personal data must not sit in a shared cache.
SENSITIVE_CACHE_CONTROL = "no-store, no-cache, must-revalidate, private"
HSTS = "max-age=31536000; includeSubDomains"

# ── L6 · Privacy: retention and classification ───────────────────────────────
#
# Retention is a property of the data class, not of a collection name, so a change
# to where something is stored cannot silently change how long it is kept.
# `None` means "no automatic expiry"; those classes are held under a legal basis
# and reviewed, never swept (see docs/security-architecture.md §5).

RETENTION_DAYS = {
    "C4": 365 * 5,   # restricted subject information — PMLA retention horizon
    "C3": 365 * 5,   # transactions — PMLA retention horizon
    "C2": 365 * 2,   # case working material
    "C1": 365,       # internal/operational
    "A0": 365 * 8,   # audit trail — must outlive everything it describes
}

# Collections whose contents are personal data, hence never loggable verbatim.
PERSONAL_DATA_COLLECTIONS = {
    "restricted_subject_information",
    "transactions",
    "entities",
    "users",
    "analyst_reports",
    "case_evidence",
    "case_notes",
}

# Fields that must be masked before leaving the server, mapped to their class.
# This is the registry that stops a new endpoint leaking an identifier: a field is
# either declared here or it is not personal data, and the test suite asserts the
# set of declared fields has not silently shrunk.
PII_FIELDS = {
    "account_number": "C3",
    "entity_name": "C3",
    "entity_id": "C1",
    "counterparty": "C3",
    "device_id": "C3",
    "email": "C3",
    "phone": "C3",
    "contact": "C3",
    "full_name": "C3",
    "customer_name": "C3",
    "ip_address": "C3",
    "date_of_birth": "C3",
    "pan": "C4",
    "aadhaar": "C4",
    "passport": "C4",
    "id_document": "C4",
    "bank_account_number": "C3",
    "beneficiary_account": "C3",
}
