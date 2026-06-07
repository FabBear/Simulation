#!/usr/bin/env python3
"""Track B Trigger: WHAT-IF bundle → load → Monte Carlo → agent_handoff_whatif.json."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools._trigger_common import (  # noqa: E402
    MAKE_WHATIF,
    RUN_MC,
    build_load_mes_cmd,
    default_suffix_pattern,
    emit_result_json,
    expand_replica_ids,
    run_step,
    validate_baseline_manifest,
    validate_bundle_not_empty,
    validate_n_runs,
)


def _build_whatif_bundle_cmd(
    python: str,
    *,
    baseline_bundle_dir: Path,
    bundle_dir: Path,
    whatif_scenario_id: str,
    baseline_scenario_id: str,
    t0: float,
    horizon: float,
    whatif_actions: Path,
    description: str,
) -> list[str]:
    return [
        python,
        str(MAKE_WHATIF),
        "--base-dir",
        str(baseline_bundle_dir.resolve()),
        "--out-dir",
        str(bundle_dir.resolve()),
        "--whatif-scenario-id",
        whatif_scenario_id,
        "--baseline-scenario-id",
        baseline_scenario_id,
        "--t0",
        str(t0),
        "--horizon",
        str(horizon),
        "--whatif-actions",
        str(whatif_actions.resolve()),
        "--description",
        description,
    ]


def _build_mc_cmd(
    python: str,
    *,
    template_id: str,
    baseline_scenario_id: str,
    reuse_baseline_manifest: Path,
    t0: float,
    horizon: float,
    n_runs: int,
    parallel: int,
    out_dir: Path,
    suffix_pattern: str,
    focus_scopes: str,
    kpi_names: str,
    level: str,
    skip_promote: bool,
    skip_sim_if_manifest_exists: bool,
    dry_run: bool,
) -> list[str]:
    cmd = [
        python,
        str(RUN_MC),
        "--track",
        "whatif",
        "--template-scenario-id",
        template_id,
        "--baseline-scenario-id",
        baseline_scenario_id,
        "--reuse-baseline-manifest",
        str(reuse_baseline_manifest.resolve()),
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
    ]
    if suffix_pattern:
        cmd.extend(["--suffix-pattern", suffix_pattern])
    if focus_scopes:
        cmd.extend(["--focus-scopes", focus_scopes])
    if kpi_names:
        cmd.extend(["--kpi-names", kpi_names])
    if level:
        cmd.extend(["--level", level])
    if skip_promote:
        cmd.append("--skip-promote")
    if skip_sim_if_manifest_exists:
        cmd.append("--skip-sim-if-manifest-exists")
    if dry_run:
        cmd.append("--dry-run")
    return cmd


def run_whatif_pipeline(args: argparse.Namespace) -> int:
    validate_n_runs(args.n_runs)
    validate_baseline_manifest(args.reuse_baseline_manifest, args.n_runs)

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle_dir = out_dir / "bundle"
    template_id = args.whatif_scenario_id.strip()
    baseline_id = args.baseline_scenario_id.strip()
    suffix_pattern = (args.suffix_pattern or "").strip() or default_suffix_pattern(template_id)
    description = args.description or "Trigger what-if pipeline bundle"

    if not args.skip_snapshot:
        if not args.whatif_actions:
            print("X --whatif-actions required unless --skip-snapshot", file=sys.stderr)
            return 1
        rc = run_step(
            _build_whatif_bundle_cmd(
                args.python,
                baseline_bundle_dir=args.baseline_bundle_dir,
                bundle_dir=bundle_dir,
                whatif_scenario_id=template_id,
                baseline_scenario_id=baseline_id,
                t0=args.t0,
                horizon=args.horizon,
                whatif_actions=args.whatif_actions,
                description=description,
            ),
            dry_run=args.dry_run,
        )
        if rc != 0:
            return rc
        if not args.dry_run:
            validate_bundle_not_empty(bundle_dir, require_whatif=True)
    elif not bundle_dir.is_dir():
        print(f"X bundle dir missing: {bundle_dir} (--skip-snapshot)", file=sys.stderr)
        return 1
    elif not args.dry_run:
        validate_bundle_not_empty(bundle_dir, require_whatif=True)

    if not args.skip_load:
        rc = run_step(
            build_load_mes_cmd(
                args.python,
                scenario_id=template_id,
                mode="WHATIF",
                t0=args.t0,
                horizon=args.horizon,
                bundle_dir=bundle_dir,
                baseline=baseline_id,
                description=description,
                include_whatif=True,
            ),
            dry_run=args.dry_run,
        )
        if rc != 0:
            return rc

    rc = run_step(
        _build_mc_cmd(
            args.python,
            template_id=template_id,
            baseline_scenario_id=baseline_id,
            reuse_baseline_manifest=args.reuse_baseline_manifest,
            t0=args.t0,
            horizon=args.horizon,
            n_runs=args.n_runs,
            parallel=args.parallel,
            out_dir=out_dir,
            suffix_pattern=suffix_pattern,
            focus_scopes=args.focus_scopes,
            kpi_names=args.kpi_names,
            level=args.level,
            skip_promote=args.skip_promote,
            skip_sim_if_manifest_exists=args.skip_sim_if_manifest_exists,
            dry_run=args.dry_run,
        ),
        dry_run=args.dry_run,
    )
    if rc != 0:
        return rc

    handoff_path = out_dir / "agent_handoff_whatif.json"
    emit_result_json(
        {
            "track": "whatif",
            "template_scenario_id": template_id,
            "baseline_scenario_id": baseline_id,
            "replica_scenario_ids": expand_replica_ids(
                template_id, suffix_pattern, args.n_runs,
            ),
            "handoff_path": str(handoff_path),
            "paired_manifest": str(out_dir / "paired_manifest.csv"),
        }
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Track B: bundle → load → MC → handoff")
    p.add_argument("--baseline-scenario-id", required=True)
    p.add_argument("--baseline-bundle-dir", type=Path, required=True)
    p.add_argument("--reuse-baseline-manifest", type=Path, required=True)
    p.add_argument("--whatif-scenario-id", required=True)
    p.add_argument("--whatif-actions", type=Path, default=None)
    p.add_argument("--t0", type=float, required=True)
    p.add_argument("--horizon", type=float, default=120.0)
    p.add_argument("--focus-scopes", default="")
    p.add_argument("--kpi-names", default="")
    p.add_argument("--level", choices=("L1", "L2", "L3"), default="L3")
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
    return run_whatif_pipeline(args)


if __name__ == "__main__":
    raise SystemExit(main())
