"""
Context Guard — demo state reset.

Live ingests accumulate transactions, and the scorer measures each new transaction
against the account's own baseline. Click through the live feed a few times and the
baseline shifts, so the coordinated scenario stops taking the same route.

Re-seeding restores the three curated scenarios, the synthetic accounts and the
default thresholds. It removes only synthetic data — anything created by a
non-synthetic account is left alone.

Used by the test suites (which need a deterministic starting point) and available
as a command:  npm run seed
"""

from config import get_db
from services.seed import seed_database
from services.users import ensure_case_assignments, ensure_users


def reset_demo_state(verbose=True):
    """Return the database to the seeded demo state. Idempotent."""
    db = get_db()
    db.users.delete_many({"is_synthetic": False})
    db.sessions.delete_many({})
    db.settings.delete_many({})
    seed_database(db)
    ensure_users(db)
    ensure_case_assignments(db)
    if verbose:
        print("  Reset to the seeded demo state (accounts, cases, thresholds)")
    return db
