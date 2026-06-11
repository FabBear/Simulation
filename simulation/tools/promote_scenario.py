#!/usr/bin/env python3
"""Promote mes_scenario.status (e.g. DRAFT → VALIDATED) for run_sim_forward_once."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database import SessionLocal
from models import MesScenario

_ALLOWED = frozenset({"DRAFT", "VALIDATED", "RUNNING", "DONE", "FAILED"})


def promote(scenario_id: str, status: str) -> int:
    status = status.upper()
    if status not in _ALLOWED:
        print(f"Invalid status {status!r}; allowed: {sorted(_ALLOWED)}", file=sys.stderr)
        return 1
    db = SessionLocal()
    try:
        sc = db.query(MesScenario).filter(MesScenario.scenario_id == scenario_id).first()
        if sc is None:
            print(f"Scenario not found: {scenario_id}", file=sys.stderr)
            return 1
        prev = sc.status
        sc.status = status
        db.commit()
        print(f"Promoted {scenario_id}: {prev} -> {status}")
        return 0
    finally:
        db.close()


def main() -> int:
    p = argparse.ArgumentParser(description="Update mes_scenario.status")
    p.add_argument("--scenario-id", required=True)
    p.add_argument("--status", default="VALIDATED", help="Target status (default VALIDATED)")
    args = p.parse_args()
    return promote(args.scenario_id, args.status)


if __name__ == "__main__":
    raise SystemExit(main())
