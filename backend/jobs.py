"""
Context Guard — Background Job Runner

The platform settles bank responses *lazily*: the next read sweeps the gateway and
delivers whatever answer has come due. That is right for a demonstration and wrong for
an unattended deployment, because if nobody opens the page, nobody delivers the answer —
and a request the bank answered sits waiting until someone happens to look.

This runner does the same work on a clock, so the state of the system does not depend on
who is watching it:

    bank gateway sweep   deliver due answers, lapse requests past their deadline
    access expiry        mark lapsed authorisations and requests expired

    python jobs.py                 # run every job once, then exit
    python jobs.py --interval 30   # run every 30 seconds until interrupted

It is deliberately idempotent: running it twice in a row changes nothing, which is what
makes it safe to run from a scheduler, a container restart, or the cron line in
docker-compose.
"""

import argparse
import sys
import time
from datetime import datetime

from config import get_db
from services import access


def sweep(db):
    """One pass over everything that expires on a clock. Returns what changed."""
    delivered, lapsed = access.expire_stale(db)
    return {
        "at": datetime.utcnow().isoformat(),
        "delivered_answers": delivered,
        "lapsed_requests": lapsed,
    }


def run_once():
    db = get_db()
    before = db.audit_log.count_documents({"action": "bank_response_deadline_expired"})
    result = sweep(db)
    after = db.audit_log.count_documents({"action": "bank_response_deadline_expired"})
    result["deadlines_enforced"] = after - before
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run Context Guard's timed jobs.")
    parser.add_argument("--interval", type=int, default=0,
                        help="seconds between runs (0 runs once and exits)")
    args = parser.parse_args(argv)

    print(f"[jobs] starting — interval {args.interval}s")
    while True:
        try:
            result = run_once()
        except Exception as exc:  # a failed pass must not stop the runner
            print(f"[jobs] pass failed: {exc}", file=sys.stderr)
        else:
            print(f"[jobs] {result['at']} delivered={result['delivered_answers']} "
                  f"lapsed={result['lapsed_requests']} "
                  f"deadlines={result['deadlines_enforced']}")

        if not args.interval:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
