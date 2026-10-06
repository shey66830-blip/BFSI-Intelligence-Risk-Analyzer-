"""
Context Guard — L1 · Response Hardening

Puts the browser-side protections on every response the API emits. The point is
that a response cannot leave without them: a new route has no way to opt out,
because the headers are attached after the handler rather than inside it.

What each one buys:

    X-Content-Type-Options: nosniff   a .json response can never be reinterpreted
                                      as HTML and executed
    X-Frame-Options / frame-ancestors  the API is never framed, so it cannot be
                                      used as a clickjacking surface
    Content-Security-Policy           this origin is not a document: no scripts,
                                      no sub-resources, nothing to exploit
    Referrer-Policy: no-referrer      a URL carrying a case id never leaks to a
                                      third party through a Referer header
    Cross-Origin-*                    the response cannot be pulled into another
                                      origin's document
    Permissions-Policy                no device capability is reachable from a
                                      page served by this origin
    Cache-Control: no-store           an unmasked payload is not left in a shared
                                      or disk cache for the next user of the machine
    Strict-Transport-Security         only under TLS: it is meaningless over http
                                      and would break plain-http development

The HTML document needs its own policy and cannot inherit this one — a document's
CSP has to arrive *with the document*. That is `security/web/security-headers.conf`.
"""

from flask import request

from . import policy


def _is_api(path):
    """Everything this application serves is the API."""
    return path.startswith("/api/")


def apply(app):
    @app.after_request
    def _harden(response):
        for name, value in policy.BASE_HEADERS.items():
            response.headers[name] = value

        if _is_api(request.path):
            # Personal data does not belong in a cache, and a JSON body is not
            # something a browser should ever reuse for a second identity.
            response.headers["Cache-Control"] = policy.SENSITIVE_CACHE_CONTROL
            response.headers["Pragma"] = "no-cache"

        # HSTS is a promise that TLS is always available. Making it over plain
        # http would either be ignored or, worse, pin a host that only speaks
        # http — so it is asserted only where it is true.
        if policy.IS_PRODUCTION:
            response.headers["Strict-Transport-Security"] = policy.HSTS

        # Do not advertise the stack. `Server` is set by the WSGI server and
        # `X-Powered-By` by some frameworks; neither helps a defender.
        response.headers.pop("X-Powered-By", None)
        return response
