#!/usr/bin/env python
"""Seed a demo dataset so the UI can be explored without running the scanner.

A thin CLI wrapper around :func:`momentum.demo.seed_all` (the seeding logic lives
in the package so it also ships in the desktop build and powers the in-app
"Load Sample Data" action). Deterministic and idempotent — the same dataset
every time, cleared before re-seeding.

    python scripts/seed_demo.py                 # seed data/momentum.db
    DATABASE_URL=sqlite:///demo.db python scripts/seed_demo.py
    python scripts/seed_demo.py --reset-only    # just delete demo rows
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from momentum.demo import reset, seed_all  # noqa: E402
from momentum.persistence.database import (  # noqa: E402
    create_all,
    create_db_engine,
    create_session_factory,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the MRP demo dataset.")
    parser.add_argument("--reset-only", action="store_true", help="Delete demo rows and exit.")
    args = parser.parse_args()

    engine = create_db_engine()
    create_all(engine)  # ensure the schema exists (idempotent)
    factory = create_session_factory(engine)

    with factory() as session:
        if args.reset_only:
            reset(session)
            session.commit()
            print("Demo rows removed.")
            return 0

        counts = seed_all(session)
        session.commit()

        print("Demo dataset seeded:")
        print(f"  market regimes     : {counts['market_regimes']}")
        print(f"  signals            : {counts['signals']}")
        print(f"  closed trades      : {counts['trades']}")
        print(f"  portfolio snapshots: {counts['portfolio_snapshots']}")
        print(f"  scan candidates    : {counts['scan_results']} (ranked)")
        print(f"  conviction scores  : {counts['conviction_scores']}")
        print(f"  opportunity tiers  : {counts['opportunity_classifications']}")
        print(f"  risk metrics       : {counts['risk_metrics']} (inception / 90d / 30d)")
        print(f"  optimization rows  : {counts['optimization_results']} (2 studies)")
        print(f"  run + audit trail  : {counts['runs']} 'demo' run (replay-ready)")
        print(f"\nDatabase: {engine.url}")
        print("Try:  mrp replay   |   mrp health   |   start the API and open the desktop app")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
