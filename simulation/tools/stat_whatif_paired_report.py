#!/usr/bin/env python3
"""CLI: Pipeline B paired what-if report (CSV + agent_handoff_whatif.json)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from stats.common import iso_now, list_paired_runs, write_json
from stats.whatif_effect import WhatifEffectConfig, run_whatif_paired_analysis, write_whatif_outputs


def main() -> int:
    p = argparse.ArgumentParser(description="Paired what-if effect report (Pipeline B)")
    p.add_argument("--paired-manifest", type=Path, required=True)
    p.add_argument("--t0", type=float, required=True)
    p.add_argument("--horizon", type=float, default=120.0)
    p.add_argument("--baseline-scenario-id", required=True)
    p.add_argument("--whatif-scenario-id", required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--level", choices=("L1", "L2", "L3"), default="L3")
    p.add_argument("--tolerance", type=float, default=1.0)
    p.add_argument("--kpi-names", default="", help="Comma-separated KPI filter")
    p.add_argument("--focus-scopes", default="", help="Comma-separated scope filter")
    p.add_argument(
        "--baseline-manifest",
        type=Path,
        default=None,
        help="Original runs_manifest path (for handoff metadata)",
    )
    p.add_argument(
        "--handoff-out",
        type=Path,
        default=None,
        help="Default: {out-dir}/agent_handoff_whatif.json",
    )
    args = p.parse_args()

    pairs = list_paired_runs(args.paired_manifest)
    if len(pairs) < 1:
        print("X no paired runs in manifest", file=sys.stderr)
        return 1

    kpi_list = [x.strip() for x in args.kpi_names.split(",") if x.strip()] or None
    focus = [x.strip() for x in args.focus_scopes.split(",") if x.strip()] or None
    cfg = WhatifEffectConfig(
        t0=args.t0,
        horizon=args.horizon,
        tolerance=args.tolerance,
        level=args.level,
        kpi_names=kpi_list,
        focus_scopes=focus,
    )
    summary = run_whatif_paired_analysis(
        pairs,
        config=cfg,
        baseline_scenario_id=args.baseline_scenario_id,
        whatif_scenario_id=args.whatif_scenario_id,
    )
    whatif_block = write_whatif_outputs(
        args.out_dir,
        summary,
        cfg=cfg,
        baseline_scenario_id=args.baseline_scenario_id,
        whatif_scenario_id=args.whatif_scenario_id,
        paired_n=len(pairs),
        paired_manifest_name=Path(args.paired_manifest).name,
        baseline_manifest_name=(
            args.baseline_manifest.name
            if args.baseline_manifest
            else "runs_manifest.csv"
        ),
    )

    handoff_path = args.handoff_out or (args.out_dir / "agent_handoff_whatif.json")
    payload = {
        "version": "1.0",
        "pipeline": "whatif",
        "target_agent": "whatif_verification",
        "generated_at": iso_now(),
        "t0_sim_minute": args.t0,
        "horizon_minutes": args.horizon,
        "paired_n": len(pairs),
        "paired_manifest": Path(args.paired_manifest).name,
        "baseline_reused_from": whatif_block.get("baseline_reused_from"),
        "whatif": whatif_block,
        "agent_notes": [
            "Paired t on D_i = whatif_i - baseline_i; same seed as runs_manifest.",
            "Does not consume g_star_kpi_evidence.",
        ],
    }
    write_json(handoff_path, payload)
    print(f"Wrote {args.out_dir / 'whatif_paired_summary.csv'} ({len(summary)} rows)")
    print(f"Handoff -> {handoff_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
