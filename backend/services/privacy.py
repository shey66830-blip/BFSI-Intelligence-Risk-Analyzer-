"""
Context Guard — Server-side Privacy Filtering

Masking used to happen in the browser, which means the raw values still travelled
to every client. Here the redaction happens *before* the response is serialised, so
an analyst's session never receives identifiers it is not entitled to see.

Policy
------
Full access (permission `txn:view_unmasked`)  → compliance, admin
Masked access (permission `txn:view`)         → analysts, when the org policy
                                                `mask_analyst_pii` is enabled
"""


def mask_name(value):
    """'Rajesh Kumar' → 'R. Kumar'"""
    if not value:
        return value
    parts = str(value).strip().split()
    if len(parts) == 1:
        return parts[0][:1] + "."
    return f"{parts[0][:1]}. {' '.join(parts[1:])}"


def mask_account(value):
    """'123456789012' → 'XXXX-9012'"""
    if not value:
        return value
    s = str(value)
    return s if len(s) <= 4 else "XXXX-" + s[-4:]


def mask_email(value):
    """'ananya.iyer@bank.in' → 'a****@bank.in'"""
    if not value or "@" not in str(value):
        return value
    local, domain = str(value).split("@", 1)
    return f"{local[:1]}****@{domain}"


def mask_device(value):
    """Device ids stay pseudonymous but are shortened to a stable handle."""
    if not value:
        return value
    s = str(value)
    return f"device-{s[-4:]}" if len(s) > 4 else s


def _released(user, permission):
    """True when a live authorisation has released this capability to the identity.

    Read from the request context when there is one (middleware resolves the grants
    once per request), and from the database otherwise, so the answer is the same
    whether masking happens inside a request or in a script.
    """
    try:
        from flask import g
        grants = getattr(g, "grants", None)
    except RuntimeError:                                  # no application context
        grants = None
    if grants is None:
        from config import get_db
        from services.access import active_unlocks
        grants = active_unlocks(get_db(), user.get("id"))
    return permission in grants


def redaction_level(user, settings):
    """Return 'full' or 'masked' for this identity."""
    from services.users import has_permission

    if has_permission(user.get("role"), "txn:view_unmasked"):
        return "full"
    # Masking is a default, not a verdict: a justified, expiring authorisation can
    # release the identifiers to an analyst without changing what their role is.
    if _released(user, "txn:view_unmasked"):
        return "full"
    if settings.get("mask_analyst_pii", True) is False:
        return "full"
    return "masked"


def mask_transaction(txn, level):
    """Return a copy of the transaction with identifiers redacted."""
    if level == "full":
        return txn

    out = dict(txn)
    redacted = []
    if out.get("entity_name"):
        out["entity_name"] = mask_name(out["entity_name"])
        redacted.append("entity_name")
    if out.get("counterparty"):
        out["counterparty"] = mask_name(out["counterparty"])
        redacted.append("counterparty")
    if out.get("account_number"):
        out["account_number"] = mask_account(out["account_number"])
        redacted.append("account_number")
    if out.get("device_id"):
        out["device_id"] = mask_device(out["device_id"])
        redacted.append("device_id")
    out["redacted_fields"] = redacted
    return out


def redact_text(text, names):
    """Replace any known entity name inside free text with its masked form.

    Case titles and descriptions are written in prose ("Rajesh Kumar — ₹3,00,000
    payment to Apollo Hospitals"), which would otherwise leak an identifier that
    the structured fields already redact. Longest names are replaced first so
    "Sharma & Associates" is not half-replaced by a shorter match.
    """
    if not text or not names:
        return text
    out = str(text)
    for name in sorted((n for n in names if n), key=len, reverse=True):
        if name in out:
            out = out.replace(name, mask_name(name))
    return out


def mask_cases(cases, level, names=None):
    """Redact owner names and free-text identifiers on a case list."""
    if level == "full":
        return cases
    for case in cases:
        if case.get("assigned_to_name"):
            case["assigned_to_name"] = mask_name(case["assigned_to_name"])
        if names:
            redacted = []
            for field in ("title", "description"):
                original = case.get(field)
                cleaned = redact_text(original, names)
                if cleaned != original:
                    case[field] = cleaned
                    redacted.append(field)
            if redacted:
                case["redacted_fields"] = sorted(set(case.get("redacted_fields", [])) | set(redacted))
    return cases
