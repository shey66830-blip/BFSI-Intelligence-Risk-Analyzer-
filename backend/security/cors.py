"""
Context Guard — L2 · Origin Trust

Closes G-01. The application previously answered `Access-Control-Allow-Origin: *`,
which means any page on the internet could call this API with a token it had
obtained — a phishing page, a malicious ad iframe, a compromised dependency in some
unrelated site.

The model here:

* **An explicit allowlist, never a wildcard.** `Access-Control-Allow-Origin` is
  never `*`, and never reflects an origin back just because it asked.
* **A denied origin is denied silently and safely** — no CORS headers are emitted,
  so the browser blocks the read. The request still reaches the handler for
  same-origin callers, which is the normal path here (Vite proxies `/api`).
* **Credentials are never allowed from an untrusted origin.**
* **Production must name its origins.** Booting production without an explicit
  allowlist is refused rather than defaulted, because "we forgot to set it" and
  "any origin may call us" must not be the same outcome.

Note on the normal path: this console reaches the API through the Vite dev proxy
and, in production, through the same origin as the static host. Those requests
carry no `Origin` header at all, so they are not CORS requests and are unaffected.
"""

from flask_cors import CORS

from . import policy


def denied(origin):
    """True when an origin is absent from the allowlist. Used by tests and logging."""
    return bool(origin) and origin.rstrip("/") not in policy.ALLOWED_ORIGINS


def apply(app):
    origins = list(policy.ALLOWED_ORIGINS)

    CORS(
        app,
        resources={r"/api/*": {"origins": origins}},
        allow_headers=["Content-Type", "Authorization", "X-Session-Token"],
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        expose_headers=["Retry-After", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
        # The session token travels in an Authorization header, which a browser
        # will only send when it is told the origin is trusted. Credentialed
        # requests are enabled *for the allowlist only* — flask-cors matches the
        # origin list before it echoes anything back.
        supports_credentials=False,
        max_age=600,
        send_wildcard=False,
        vary_header=True,
    )
