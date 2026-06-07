#!/usr/bin/env python3
"""Track A Trigger: FORWARD snapshot → load → Monte Carlo → agent_handoff_g_star_analysis.json."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools._trigger_common import (  # noqa: E402
    BUILD_FORWARD,
    RUN_MC,
    build_load_mes_cmd,
    default_suffix_pattern,
    emit_result_json,
    expand_replica_ids,
    run_step,
    validate_bundle_not_empty,
    validate_n_runs,
)


def _build_forward_cmd(
    python: str,
    *,
    sim_csv_dir: Path,
    run_id: str,
    t0: float,
    horizon: float,
    scenario_id: str,
    bundle_dir: Path,
    description: str,
) -> list[str]:
    return [
        python,
        str(BUILD_FORWARD),
        "--sim-csv-dir",
        str(sim_csv_dir.resolve()),
        "--run-id",
        run_id,
        "--t0",
        str(t0),
        "--horizon",
        str(horizon),
        "--scenario-id",
        scenario_id,
        "--out-dir",
        str(bundle_dir.resolve()),
        "--description",
        description,
    ]


def _build_mc_cmd(
    python: str,
    *,
    template_id: str,
    t0: float,
    horizon: float,
    n_runs: int,
    parallel: int,
    out_dir: Path,
    g_star_file: Path,
    suffix_pattern: str,
    baseline_csv_dir: Path | None,
    anchor_tg: str,
    skip_promote: bool,
    skip_sim_if_manifest_exists: bool,
    dry_run: bool,
) -> list[str]:
    cmd = [
        python,
        str(RUN_MC),
        "--track",
        "g_star_analysis",
        "--template-scenario-id",
        template_id,
        "--t0",
        str(t0),
        "--horizon",
        str(horizon),
        "--n-runs",
        str(n_runs),
        "--parallel",
        str(parallel),
        "--out-dir",
        str(out_dir.resolve()),
        "--g-star-file",
        str(g_star_file.resolve()),
    ]
    if suffix_pattern:
        cmd.extend(["--suffix-pattern", suffix_pattern])
    if baseline_csv_dir:
        cmd.extend(["--baseline-csv-dir", str(baseline_csv_dir.resolve())])
    if anchor_tg:
        cmd.extend(["--anchor-tg", anchor_tg])
    if skip_promote:
        cmd.append("--skip-promote")
    if skip_sim_if_manifest_exists:
        cmd.append("--skip-sim-if-manifest-exists")
    if dry_run:
        cmd.append("--dry-run")
    return cmd


def run_forward_pipeline(args: argparse.Namespace) -> int:
    validate_n_runs(args.n_runs)
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle_dir = out_dir / "bundle"
    template_id = args.scenario_id.strip()
    suffix_pattern = (args.suffix_pattern or "").strip() or default_suffix_pattern(template_id)
    description = args.description or "Trigger forward pipeline bundle"

    if not args.skip_snapshot:
        if not args.run_id:
            print("X --run-id required unless --skip-snapshot", file=sys.stderr)
            return 1
        sim_csv_dir = args.sim_csv_dir.resolve()
        rc = run_step(
            _build_forward_cmd(
                args.python,
                sim_csv_dir=sim_csv_dir,
                run_id=args.run_id,
                t0=args.t0,
                horizon=args.horizon,
                scenario_id=template_id,
                bundle_dir=bundle_dir,
                description=description,
            ),
            dry_run=args.dry_run,
        )
        if rc != 0:
            return rc
        if not args.dry_run:
            validate_bundle_not_empty(bundle_dir)
    elif not bundle_dir.is_dir():
        print(f"X bundle dir missing: {bundle_dir} (--skip-snapshot)", file=sys.stderr)
        return 1
    elif not args.dry_run:
        validate_bundle_not_empty(bundle_dir)

    if not args.skip_load:
        rc = run_step(
            build_load_mes_cmd(
                args.python,
                scenario_id=template_id,
                mode="FORWARD",
                t0=args.t0,
                horizon=args.horizon,
                bundle_dir=bundle_dir,
                description=description,
            ),
            dry_run=args.dry_run,
        )
        if rc != 0:
            return rc

    rc = run_step(
        _build_mc_cmd(
            args.python,
            template_id=template_id,
            t0=args.t0,
            horizon=args.horizon,
            n_runs=args.n_runs,
            parallel=args.parallel,
            out_dir=out_dir,
            g_star_file=args.g_star_file,
            suffix_pattern=suffix_pattern,
            baseline_csv_dir=args.baseline_csv_dir,
            anchor_tg=args.anchor_tg,
            skip_promote=args.skip_promote,
            skip_sim_if_manifest_exists=args.skip_sim_if_manifest_exists,
            dry_run=args.dry_run,
        ),
        dry_run=args.dry_run,
    )
    if rc != 0:
        return rc

    handoff_path = out_dir / "agent_handoff_g_star_analysis.json"
    emit_result_json(
        {
            "track": "g_star_analysis",
            "template_scenario_id": template_id,
            "replica_scenario_ids": expand_replica_ids(
                template_id, suffix_pattern, args.n_runs,
            ),
            "handoff_path": str(handoff_path),
            "runs_manifest": str(out_dir / "runs_manifest.csv"),
        }
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Track A: snapshot → load → MC → handoff")
    p.add_argument("--sim-csv-dir", type=Path, default=None)
    p.add_argument("--run-id", default="")
    p.add_argument("--t0", type=float, required=True)
    p.add_argument("--horizon", type=float, default=120.0)
    p.add_argument("--scenario-id", required=True, help="FORWARD template scenario_id")
    p.add_argument("--g-star-file", type=Path, required=True)
    p.add_argument("--baseline-csv-dir", type=Path, default=None)
    p.add_argument("--anchor-tg", default="")
    p.add_argument("--n-runs", type=int, default=30)
    p.add_argument("--parallel", type=int, default=4)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--suffix-pattern", default="")
    p.add_argument("--description", default="")
    p.add_argument("--python", default=sys.executable)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--skip-snapshot", action="store_true")
    p.add_argument("--skip-load", action="store_true")
    p.add_argument("--skip-promote", action="store_true")
    p.add_argument("--skip-sim-if-manifest-exists", action="store_true")
    args = p.parse_args()

    if not args.skip_snapshot and args.sim_csv_dir is None:
        print("X --sim-csv-dir required unless --skip-snapshot", file=sys.stderr)
        return 1

    return run_forward_pipeline(args)


if __name__ == "__main__":
    raise SystemExit(main())
