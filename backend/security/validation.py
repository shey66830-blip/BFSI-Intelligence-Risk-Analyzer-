"""
Context Guard — L3 · Central Input Validation

Closes the exploitable half of G-10.

Every route in this application reads its body ad hoc — `data.get("username")`,
`data.get("status")` — and passes values into MongoDB queries. That is safe only as
long as no caller ever sends a *key* the route did not expect, because the dangerous
inputs here are not string values, they are structure:

    {"username": {"$ne": null}}        a MongoDB operator, evaluated as a query
    {"username": {"$gt": ""}}          matches the first user in the collection
    {"__proto__": {"isAdmin": true}}   prototype pollution on the client side
    {"a": {"a": {"a": ... }}}          a parse bomb that costs the server the stack

A route cannot defend against that by validating "the fields I know about", because
the attack is the field it did not think of. So the defence is central and negative:
reject the shapes that have no legitimate use in this application's API, once, for
every route, including routes written later.

What is rejected
----------------
* any key beginning with `$` — MongoDB operator syntax, never a real field name
* `__proto__`, `constructor`, `prototype` — prototype-pollution vectors
* a body larger than `MAX_BODY_BYTES` (enforced by Flask as 413)
* nesting deeper than `MAX_JSON_DEPTH`
* a single string longer than `MAX_STRING_LENGTH`

What is deliberately **not** rejected
-------------------------------------
Unknown-but-harmless fields. Refusing them is the textbook answer and it breaks
real clients: the console sends back documents it read, and forward-compatible
callers legitimately send extra keys. The dangerous surface is operators and
prototype keys, and that is what is closed here. Field-level schema enforcement
belongs per-route, where the route knows its own contract.
"""

from flask import jsonify, request

from . import policy


class Rejected(Exception):
    """A payload failed the central guard. Carries a message safe to return."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _walk(value, depth):
    """Raise Rejected if a decoded value contains a forbidden key or is too deep."""
    if depth > policy.MAX_JSON_DEPTH:
        raise Rejected(f"Payload is nested more than {policy.MAX_JSON_DEPTH} levels deep.")

    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise Rejected("Object keys must be strings.")
            if key in policy.FORBIDDEN_KEYS:
                raise Rejected(f"The key {key!r} is not accepted.")
            if key.startswith(policy.FORBIDDEN_KEY_PREFIXES):
                raise Rejected(f"A key beginning with {key[0]!r} is not accepted.")
            _walk(child, depth + 1)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _walk(child, depth + 1)
    elif isinstance(value, str):
        if len(value) > policy.MAX_STRING_LENGTH:
            raise Rejected("A string field is longer than the permitted maximum.")


def validate_payload(value):
    """Validate an already-decoded value. Exposed so services can reuse the rule."""
    _walk(value, 0)
    return value


def apply(app):
    # Flask enforces this before the body is read, so an oversized request is
    # refused with 413 without ever being parsed. The handler below adds the
    # structured-error equivalent for operator and depth attacks.
    app.config["MAX_CONTENT_LENGTH"] = policy.MAX_BODY_BYTES
    app.config["JSON_SORT_KEYS"] = False

    @app.before_request
    def _validate():
        if not request.path.startswith("/api/"):
            return None

        # Query strings and form fields are just as much attacker-controlled keys
        # as a JSON body, and they reach the same handlers.
        for source in (request.args, request.form):
            try:
                _walk({k: v for k, v in source.items(multi=True)}, 0)
            except Rejected as rejected:
                return jsonify({"error": rejected.reason, "code": "invalid_request"}), 400

        if request.is_json:
            payload = request.get_json(silent=True)
            if payload is not None:
                try:
                    validate_payload(payload)
                except Rejected as rejected:
                    return jsonify({"error": rejected.reason, "code": "invalid_request"}), 400

        return None

    @app.errorhandler(413)
    def _too_large(_error):
        return jsonify({
            "error": "The request body is larger than the permitted maximum.",
            "code": "payload_too_large",
        }), 413
