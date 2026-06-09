#!/usr/bin/env python3
"""
Build WHAT-IF scenario by cloning baseline mes_* from DB and applying actions.

No local CSV bundle — persists directly to Postgres (mirrors make_whatif_scenario_bundle.py).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from load_mes_scenario import persist_whatif_from_db  # noqa: E402


def build_and_persist_from_db(
    baseline_scenario_id: str,
    whatif_scenario_id: str,
    t0: float,
    horizon: float,
    description: str,
    *,
    whatif_actions_path: Path | None = None,
    plan_patch_path: Path | None = None,
) -> dict:
    return persist_whatif_from_db(
        baseline_scenario_id,
        whatif_scenario_id,
        t0,
        horizon,
        description,
        whatif_actions_path=whatif_actions_path,
        plan_patch_path=plan_patch_path,
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Build WHAT-IF scenario from DB baseline clone")
    p.add_argument("--baseline-scenario-id", required=True)
    p.add_argument("--whatif-scenario-id", required=True)
    p.add_argument("--t0", type=float, required=True)
    p.add_argument("--horizon", type=float, default=120.0)
    p.add_argument("--whatif-actions", type=Path, default=None, help="mes_whatif_action CSV or JSON")
    p.add_argument("--plan-patch", type=Path, default=None, help="Optional release plan patch CSV/JSON")
    p.add_argument("--description", default="WHAT-IF from make_whatif_scenario_from_db.py")
    args = p.parse_args()

    try:
        result = build_and_persist_from_db(
            args.baseline_scenario_id.strip(),
            args.whatif_scenario_id.strip(),
            float(args.t0),
            float(args.horizon),
            args.description,
            whatif_actions_path=args.whatif_actions,
            plan_patch_path=args.plan_patch,
        )
    except Exception as exc:
        print(f"X {exc}", file=sys.stderr)
        return 1

    cloned = result["cloned"]
    print(f"Persisted WHATIF scenario {result['whatif_scenario_id']} (baseline {result['baseline_scenario_id']})")
    print(
        f"  wip={cloned.get('mes_wip_snapshot', 0)} "
        f"tools={cloned.get('mes_tool_snapshot', 0)} "
        f"queues={cloned.get('mes_tool_queue_snapshot', 0)} "
        f"releases={cloned.get('mes_lot_release_plan', 0)} "
        f"cqt={cloned.get('mes_cqt_snapshot', 0)} "
        f"actions={result['actions']}"
    )
    for w in result.get("compat_warnings", [])[:10]:
        print(f"  compat: {w}")
    print("Next:")
    print(f"  python tools/promote_scenario_validated.py --scenario-id {args.whatif_scenario_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
