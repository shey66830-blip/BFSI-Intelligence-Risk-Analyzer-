"""
Context Guard — Security Package

The application-layer security controls, in one installable place.

    from security import install
    install(app)

That single call wires every control listed below. It exists so that "is this app
protected?" has a one-line answer that can be read in a diff, rather than being a
property scattered across middleware, config and twelve route files.

    L1  headers.py         browser-facing response hardening, strict API CSP
    L2  cors.py            explicit origin allowlist, never a wildcard
    L3  ratelimit.py       per-IP, per-account and per-write throttling
    L3  validation.py      operator-key, prototype and oversized-payload rejection
    L3  posture.py         refuses to boot a demo-grade configuration in production
    L6  classification.py  personal-data registry and retention policy
    L6  logguard.py        scrubs personal data out of log output

What this package deliberately does not do
------------------------------------------
It does not re-implement controls that already exist and are already guarded:
credential hashing, opaque hashed sessions, the permission matrix, capability
grants, separation of duties, response masking, or the tamper-evident audit chain.
Those live in `services/` and are asserted by `test_security.py`. Duplicating them
here would create two sources of truth for the same decision, which is how a
control silently diverges from its copy.

It also cannot close the infrastructure gaps — database authentication, encryption
at rest, SIEM export, supply chain. Those are deployment controls; pretending
otherwise in code would be security theatre. See docs/security-architecture.md §6.

Enforcement policy
------------------
Every control here **enforces**. There is no environment flag that switches one
off. The only variation between environments is scope, not strength: development
serves a Vite HMR preamble and production does not, so the document policy differs
— and that policy is served at the static host (`security/web/`), not from here.
"""

from . import classification, cors, headers, logguard, policy, posture, ratelimit, validation
from .posture import InsecurePosture, assert_posture
from .ratelimit import LIMITER

__all__ = [
    "install",
    "assert_posture",
    "InsecurePosture",
    "LIMITER",
    "classification",
    "cors",
    "headers",
    "logguard",
    "policy",
    "posture",
    "ratelimit",
    "validation",
]


def install(app):
    """Attach every application-layer control to a Flask app.

    Order is not arbitrary: CORS is registered first so its preflight response is
    the one the headers layer then decorates, and validation runs before
    throttling would matter — a rejected payload should not consume budget that a
    legitimate request then has to wait for.
    """
    cors.apply(app)          # L2 — must answer preflights before anything rejects them
    validation.apply(app)    # L3 — cheap structural rejection
    ratelimit.apply(app)     # L3 — budget accounting
    headers.apply(app)       # L1 — last, so it decorates every response above
    logguard.apply(app)      # L6 — output-side, order irrelevant
    return app
