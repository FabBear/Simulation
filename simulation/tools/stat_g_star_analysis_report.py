#!/usr/bin/env python3
"""CLI: Pipeline A G* KPI analysis report (CSV + agent_handoff_g_star_analysis.json)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from stats.common import iso_now, list_run_dirs, load_g_star, write_json
from stats.g_star_analysis import (
    GStarAnalysisConfig,
    run_g_star_analysis,
    write_g_star_analysis_outputs,
)

_DEFAULT_KPIS = "q_time_min,wait_ratio,wip,available_tool_ratio,utilization_avg"


def main() -> int:
    p = argparse.ArgumentParser(
        description="G* KPI root-cause analysis: historical 2h-diff vs FORWARD t-test"
    )
    p.add_argument("--runs-manifest", type=Path, required=True)
    p.add_argument("--g-star-file", type=Path, required=True)
    p.add_argument("--baseline-csv-dir", type=Path, required=True)
    p.add_argument("--t0", type=float, required=True)
    p.add_argument("--horizon", type=float, default=120.0)
    p.add_argument("--n-runs", type=int, default=30)
    p.add_argument("--anchor-tg", default="")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--alpha", type=float, default=0.05)
    p.add_argument("--independence-alpha", type=float, default=0.01)
    p.add_argument("--lb-lags", type=int, default=10)
    p.add_argument("--n-diff", type=int, default=30)
    p.add_argument("--multipletest", default="fdr_bh", choices=("fdr_bh", "bonferroni", "none"))
    p.add_argument("--kpis", default=_DEFAULT_KPIS)
    p.add_argument("--tolerance", type=float, default=1.0)
    p.add_argument("--handoff-out", type=Path, default=None)
    args = p.parse_args()

    runs = list_run_dirs(args.runs_manifest)
    if len(runs) < 2:
        print(f"X need at least 2 runs, got {len(runs)}", file=sys.stderr)
        return 1
    runs = runs[: args.n_runs]

    g_star = load_g_star(args.g_star_file)
    anchor = args.anchor_tg.strip() or None
    kpis = tuple(k.strip() for k in args.kpis.split(",") if k.strip())

    cfg = GStarAnalysisConfig(
        t0=args.t0,
        horizon=args.horizon,
        tolerance=args.tolerance,
        alpha=args.alpha,
        independence_alpha=args.independence_alpha,
        lb_lags=args.lb_lags,
        n_diff=args.n_diff,
        multipletest=args.multipletest,
        kpis=kpis,
    )

    summary = run_g_star_analysis(
        runs,
        g_star,
        baseline_csv_dir=args.baseline_csv_dir,
        anchor_tg=anchor,
        config=cfg,
    )

    anchor_out = anchor or (sorted(g_star)[0] if g_star else "")
    analysis_block = write_g_star_analysis_outputs(
        args.out_dir,
        summary,
        cfg=cfg,
        g_star=g_star,
        anchor_tg=anchor_out,
        n_runs=len(runs),
        runs_manifest_name=Path(args.runs_manifest).name,
        baseline_csv_dir=str(args.baseline_csv_dir),
    )

    g_star_sorted = sorted(g_star)
    evidence_n = int((summary["in_g_star"] == 1).sum())

    handoff_path = args.handoff_out or (args.out_dir / "agent_handoff_g_star_analysis.json")
    payload = {
        "version": "1.0",
        "pipeline": "g_star_analysis",
        "target_agent": "root_cause",
        "generated_at": iso_now(),
        "t0_sim_minute": args.t0,
        "horizon_minutes": args.horizon,
        "n_runs": len(runs),
        "label_rule": "assign_bottleneck_labels / REPORT §4.3",
        "g_star_toolgroups": g_star_sorted,
        "runs_manifest": Path(args.runs_manifest).name,
        "g_star_analysis": analysis_block,
        "agent_notes": [
            "G* = ML alarm at T0 predicting bottleneck at T0+horizon.",
            "Analysis pool = G* only; non-G* rows in summary are status=not_in_g_star (reference).",
            "Handoff includes ALL G* x KPI evidence (t_p_adj, delta_mean) regardless of kpi_significant.",
            "p-values BH-FDR corrected within G* x KPI only.",
        ],
    }
    write_json(handoff_path, payload)

    print(f"Wrote {args.out_dir / 'g_star_analysis_summary.csv'} ({len(summary)} rows)")
    print(f"G* evidence rows: {evidence_n} -> {handoff_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
