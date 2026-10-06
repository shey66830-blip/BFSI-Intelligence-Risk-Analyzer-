"""
Re-seed the Context Guard demo dataset.

    cd backend && python reset_demo.py       # or: npm run seed

Restores the three curated scenarios, the synthetic role accounts, the case
assignments and the default thresholds. Run it before a demo if the live feed has
been clicked through a few times, since each simulated transaction shifts the
baseline that later scores are measured against.
"""

import sys

# The banner uses box-drawing characters; Windows consoles default to cp1252.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app import init_database
from services.reset import reset_demo_state


def main():
    print("── Resetting the demo dataset ────────────────────────────────")
    reset_demo_state()
    init_database()
    print("Done. Sign in at http://127.0.0.1:3000 with one of the synthetic accounts")
    print("listed on the login page (analyst / analyst123, compliance / compliance123,")
    print("admin / admin123).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
