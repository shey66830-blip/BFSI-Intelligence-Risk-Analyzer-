"""
Context Guard — L6 · Data Classification and Retention

Privacy work that the masking layer cannot do on its own.

`services/privacy.py` answers "should this value be masked for this caller?" — a
question about one response. It cannot answer the questions a regulator asks:

    What personal data do you hold?         → a registry, not a guess
    Why may you hold it?                    → a class, and therefore a basis
    How long will you keep it?              → a retention period per class
    Is this field personal at all?          → declared, or it is not

This module is the registry those questions are answered from. It closes the part
of G-11 that application code can close (a retention *policy* and a field
classification); the sweeper that deletes on schedule and the data-principal
request path remain open and are recorded in the architecture document.

Why a registry rather than a convention
--------------------------------------
The failure this prevents is specific: a new field is added, a new endpoint returns
it, nobody remembers it is personal data, and it travels unmasked. With the field
declared here, `assert_registry_intact()` fails the build when the declared set
changes, so adding personal data becomes a deliberate, reviewed act.
"""

from . import policy


def classify(field):
    """The data class of a field, or None when it is not personal data."""
    return policy.PII_FIELDS.get(field)


def is_personal(field):
    return field in policy.PII_FIELDS


def restricted_fields():
    """Fields at C4 — the ones that need a capability grant, not just masking."""
    return {f for f, cls in policy.PII_FIELDS.items() if cls == "C4"}


def retention_days(data_class):
    """How long a class may be kept. `None` means held under a legal basis."""
    return policy.RETENTION_DAYS.get(data_class)


def personal_fields_in(record, prefix=""):
    """Which declared personal fields a record carries. Used by tests and by the
    audit layer to describe a record without reproducing it."""
    if not isinstance(record, dict):
        return []
    found = []
    for key, value in record.items():
        path = f"{prefix}.{key}" if prefix else key
        if value in (None, "", [], {}):
            continue
        if is_personal(key):
            found.append(path)
        elif isinstance(value, dict):
            found.extend(personal_fields_in(value, path))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    found.extend(personal_fields_in(item, f"{path}[{index}]"))
    return found


def describe(record):
    """A shape summary that is safe to log: which personal fields are present,
    never their values. This is what an audit entry should carry when it needs to
    say 'this record contains a PAN' without copying the PAN."""
    return {
        "personal_field_count": len(personal_fields_in(record)),
        "personal_fields": sorted(personal_fields_in(record)),
    }


def assert_registry_intact(expected):
    """Fail loudly if the declared registry has shrunk.

    Called from the test suite with the field set it expects. A removal is not
    forbidden, but it must be accompanied by a deliberate edit to the expectation —
    which is the review step, and the whole point.
    """
    missing = set(expected) - set(policy.PII_FIELDS)
    if missing:
        raise AssertionError(
            "Personal-data fields were removed from the classification registry "
            f"without review: {sorted(missing)}"
        )
    return True


def retention_summary():
    """The retention position, for the operations screen and for reviewers."""
    return {
        "classes": {
            cls: {
                "retention_days": days,
                "fields": sorted(f for f, c in policy.PII_FIELDS.items() if c == cls),
            }
            for cls, days in policy.RETENTION_DAYS.items()
        },
        "personal_field_total": len(policy.PII_FIELDS),
        "restricted_field_total": len(restricted_fields()),
    }
