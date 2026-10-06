"""
Context Guard — L6 · Log Scrubbing

Closes the "PII in logs" half of G-11.

A log file is the least-protected copy of your data. It is written to a path that
is often world-readable, shipped to a third-party aggregator, backed up, and kept
for years — and it is written by code that is *trying to be helpful*, so it prints
whole records. The audit trail is deliberately excluded from this concern: it is a
purpose-built, access-controlled, hash-chained record. A debug log is neither.

Two passes, because there are two ways data leaks into a line
-------------------------------------------------------------
1. **By value.** An account number, a PAN, an email or a phone number is
   recognisable by its shape wherever it appears, even in a message nobody
   anticipated. Pattern pass.
2. **By name.** `entity_name='Apollo Hospitals'` is only recognisable if you know
   `entity_name` is personal — which is exactly what the classification registry
   knows. Field-aware pass.

The filter preserves the *shape* of what it redacts (`XXXX-9012`, `a****@b.in`) so a
log line stays diagnostically useful: you can still see that a value was present,
differentiate two values, and correlate a failure, without holding the value itself.

Honest limitation: pattern matching is not a guarantee. It catches the formats this
platform handles and the field names it declares. A future field holding personal
data in an unrecognised format would pass through — which is why the classification
registry is the primary control and this is the safety net behind it.
"""

import logging
import re

from . import policy

# What the value is replaced with, per pass.
REDACTED = "[redacted]"

# ── Pass 1 · recognisable values ─────────────────────────────────────────────

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
# Indian PAN: five letters, four digits, one letter.
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
# Indian mobile: starts 6-9, ten digits.
_PHONE = re.compile(r"\b[6-9]\d{9}\b")
# Long digit runs: account numbers, card numbers, Aadhaar. Deliberately >=9 so
# ordinary quantities, ports, years and amounts are left readable.
_LONG_DIGITS = re.compile(r"\b\d{9,18}\b")
# An IPv4 address is personal data under DPDP when it identifies a principal.
_IPV4 = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")

# Loopback is operational, not personal — masking it would make logs useless
# without protecting anybody.
_IP_ALLOWLIST = {"127.0.0.1", "0.0.0.0", "255.255.255.255"}


def _mask_email(match):
    local, _, domain = match.group(0).partition("@")
    return f"{local[:1]}****@{domain}"


def _mask_digits(match):
    value = match.group(0)
    return "XXXX-" + value[-4:] if len(value) > 4 else REDACTED


def _mask_ip(match):
    value = match.group(0)
    if value in _IP_ALLOWLIST:
        return value
    head = value.rsplit(".", 1)[0]
    return f"{head}.x"


# ── Pass 2 · declared personal field names ───────────────────────────────────

# Matches `entity_name=...`, `"entity_name": "..."`, `'account_number': '...'`.
# The name is kept; only the assigned value is replaced.
#
# The quoted and unquoted cases are alternated rather than unified, because a
# quoted value may legitimately contain spaces (`entity_name='Apollo Hospitals'`)
# while an unquoted one ends at the first delimiter. A single unquoted-only
# pattern silently failed to redact every multi-word name in prose.
_FIELD = re.compile(
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?P<sep>\s*[:=]\s*)"
    r"(?:(?P<q>['\"])(?P<qv>[^'\"\n]*)(?P=q)|(?P<uv>[^'\"\,;\s\)\]\}]+))"
)


def scrub(text):
    """Return `text` with personal values removed. Exposed for direct use and tests."""
    if not text:
        return text
    out = str(text)

    # Values first, so a shape is masked even when its field name is unknown.
    out = _EMAIL.sub(_mask_email, out)
    out = _PAN.sub("XXXXX0000X", out)
    out = _LONG_DIGITS.sub(_mask_digits, out)
    out = _PHONE.sub(_mask_digits, out)
    out = _IPV4.sub(_mask_ip, out)

    # Then names, which catches values that carry no distinguishing shape at all
    # — a person's name, a free-text contact.
    def _by_name(match):
        if not policy.PII_FIELDS.get(match.group("name")):
            return match.group(0)
        quote = match.group("q") or ""
        return (
            f"{match.group('name')}{match.group('sep')}"
            f"{quote}{REDACTED}{quote}"
        )

    return _FIELD.sub(_by_name, out)


class ScrubFilter(logging.Filter):
    """Scrubs every record before a handler formats it.

    Applied as a filter rather than by overriding a formatter so it also covers
    records that reach a handler through a library's own logger.
    """

    def filter(self, record):
        try:
            if isinstance(record.msg, str) and record.msg:
                if record.args:
                    # A deferred message hides its value in the arguments:
                    #
                    #     logger.info("opened for entity_name=%s", "Rajesh Kumar")
                    #
                    # The field name is in the template and the personal value is
                    # in the args, so neither can be judged alone. Materialise the
                    # message, scrub that, and clear the args.
                    #
                    # Clearing them is not tidiness. Scrubbing the template alone
                    # rewrote `entity_name=%s` into `entity_name=[redacted]` while
                    # leaving one argument queued, so the handler's own `msg % args`
                    # then raised `TypeError: not all arguments converted` — a scrub
                    # that silently breaks logging is worse than the leak it fixed.
                    try:
                        combined = record.getMessage()
                    except Exception:
                        # The caller's template did not match its own arguments;
                        # that is their bug to see, so keep the template verbatim
                        # and let the shape pass below handle it.
                        combined = record.msg
                    record.msg = scrub(combined)
                    record.args = ()
                else:
                    record.msg = scrub(record.msg)
            if record.exc_text:
                record.exc_text = scrub(record.exc_text)
        except Exception:                                  # never break logging on a scrub bug
            return True
        return True


def apply(app=None):
    """Attach the filter to the loggers that carry application and request output."""
    guard = ScrubFilter()
    for name in ("", "werkzeug", "app", "context_guard"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, ScrubFilter) for f in logger.filters):
            logger.addFilter(guard)

    if app is not None:
        app.logger.addFilter(ScrubFilter())
    return guard
