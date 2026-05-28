#!/usr/bin/env python3
"""Set mes_scenario.status to VALIDATED (operator / pipeline step)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database import SessionLocal
from models import MesScenario


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--scenario-id", required=True)
    args = p.parse_args()
    db = SessionLocal()
    try:
        sc = db.query(MesScenario).filter(MesScenario.scenario_id == args.scenario_id).first()
        if not sc:
            print(f"X not found: {args.scenario_id}", file=sys.stderr)
            return 1
        sc.status = "VALIDATED"
        db.commit()
        print(f"OK {args.scenario_id} -> VALIDATED")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
