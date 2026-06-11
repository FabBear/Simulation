#!/usr/bin/env python3
"""Monte Carlo orchestration: clone template → N replicas → run_stat_batch."""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database import SessionLocal
from stats.common import list_run_dirs

_CLONE = Path(__file__).resolve().parent / "clone_mes_scenarios_for_monte_carlo.py"
_BATCH = Path(__file__).resolve().parent / "run_stat_batch.py"


def _load_clone():
    spec = importlib.util.spec_from_file_location("clone_mes_scenarios_for_monte_carlo", _CLONE)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _count_ok_manifest(path: Path) -> int:
    if not path.is_file():
        return 0
    return sum(1 for r in list_run_dirs(path) if (r.status or "ok") == "ok")


def _resolve_suffix_pattern(args: argparse.Namespace) -> str:
    pattern = (args.suffix_pattern or "").strip()
    if pattern:
        return pattern
    template = args.template_scenario_id.strip()
    return f"{template}_R{{run:02d}}"


def _whatif_suffix_for_batch(args: argparse.Namespace, pattern: str) -> str:
    """run_stat_batch whatif pattern may differ from clone {source} pattern."""
    if "{source}" in pattern or "{template}" in pattern:
        return pattern.replace("{source}", args.template_scenario_id).replace(
            "{template}", args.template_scenario_id
        )
    return pattern


def _baseline_suffix_for_batch(args: argparse.Namespace, pattern: str) -> str:
    if "{source}" in pattern or "{template}" in pattern:
        return pattern.replace("{source}", args.template_scenario_id).replace(
            "{template}", args.template_scenario_id
        )
    return pattern


def _run_clone_step(args: argparse.Namespace, out_dir: Path, pattern: str) -> Path:
    clone_mod = _load_clone()
    manifest_path = out_dir / "clone_manifest.json"
    if args.skip_clone:
        print("Skip clone (--skip-clone)")
        return manifest_path

    replica_ids = clone_mod.expand_replica_scenario_ids(
        args.template_scenario_id, pattern, args.n_runs,
    )

    if args.skip_clone_if_exists:
        db = SessionLocal()
        try:
            if clone_mod.replica_ids_exist(db, replica_ids):
                print(f"Skip clone: all {len(replica_ids)} replicas exist in DB")
                if not manifest_path.is_file():
                    manifest_path.write_text(
                        json.dumps(
                            {
                                "source_scenario_id": args.template_scenario_id,
                                "n_runs": args.n_runs,
                                "suffix_pattern": pattern,
                                "replica_scenario_ids": replica_ids,
                                "skipped": True,
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                return manifest_path
        finally:
            db.close()

    clone_mod.run_clone(
        source_scenario_id=args.template_scenario_id,
        suffix_pattern=pattern,
        n_runs=args.n_runs,
        on_conflict=args.on_conflict,
        dry_run=False,
        manifest_out=manifest_path,
    )
    return manifest_path


def _run_batch(args: argparse.Namespace, out_dir: Path, clone_manifest: Path) -> int:
    pattern = _resolve_suffix_pattern(args)
    cmd = [
        args.python,
        str(_BATCH),
        "--t0",
        str(args.t0),
        "--horizon",
        str(args.horizon),
        "--n-runs",
        str(args.n_runs),
        "--parallel",
        str(args.parallel),
        "--out-dir",
        str(out_dir),
        "--template-scenario-id",
        args.template_scenario_id,
        "--clone-manifest",
        str(clone_manifest.relative_to(out_dir))
        if clone_manifest.is_relative_to(out_dir)
        else str(clone_manifest),
    ]
    if args.skip_promote:
        cmd.append("--skip-promote")
    if args.skip_sim_if_manifest_exists:
        cmd.append("--skip-sim-if-manifest-exists")
    if args.dry_run:
        cmd.append("--dry-run")

    track = args.track
    if track == "whatif":
        if not args.reuse_baseline_manifest:
            print("X --reuse-baseline-manifest required for whatif track", file=sys.stderr)
            return 1
        manifest = args.reuse_baseline_manifest.resolve()
        ok = _count_ok_manifest(manifest)
        if ok < args.n_runs:
            print(
                f"X baseline manifest {manifest} has {ok} ok rows, need {args.n_runs}",
                file=sys.stderr,
            )
            return 1
        wf_pattern = _whatif_suffix_for_batch(args, pattern)
        cmd.extend(
            [
                "--mode",
                "whatif",
                "--reuse-baseline-manifest",
                str(manifest),
                "--baseline-scenario-id",
                args.baseline_scenario_id,
                "--whatif-scenario-id",
                args.template_scenario_id,
                "--whatif-suffix-pattern",
                wf_pattern,
            ]
        )
        if args.focus_scopes:
            cmd.extend(["--focus-scopes", args.focus_scopes])
        if args.kpi_names:
            cmd.extend(["--kpi-names", args.kpi_names])
        if args.level:
            cmd.extend(["--level", args.level])
    elif track == "g_star_analysis":
        if not args.g_star_file:
            print("X --g-star-file required for g_star_analysis track", file=sys.stderr)
            return 1
        bl_pattern = _baseline_suffix_for_batch(args, pattern)
        cmd.extend(
            [
                "--mode",
                "g_star_analysis",
                "--g-star-file",
                str(args.g_star_file.resolve()),
                "--baseline-scenario-id",
                args.template_scenario_id,
            ]
        )
        if bl_pattern != args.template_scenario_id:
            cmd.extend(["--scenario-suffix-pattern", bl_pattern])
        if args.baseline_csv_dir:
            cmd.extend(["--baseline-csv-dir", str(args.baseline_csv_dir.resolve())])
        if args.anchor_tg:
            cmd.extend(["--anchor-tg", args.anchor_tg])
    else:
        print(f"X unknown track {track!r}", file=sys.stderr)
        return 1

    print(" ".join(cmd))
    if args.dry_run and args.clone_only:
        return 0
    proc = subprocess.run(cmd, cwd=str(_ROOT))
    return proc.returncode


def main() -> int:
    p = argparse.ArgumentParser(description="Monte Carlo: clone + stat batch")
    p.add_argument(
        "--track",
        choices=("whatif", "g_star_analysis"),
        required=True,
    )
    p.add_argument("--template-scenario-id", required=True)
    p.add_argument("--suffix-pattern", default="", help="Default: {template}_R{run:02d}")
    p.add_argument("--t0", type=float, required=True)
    p.add_argument("--horizon", type=float, default=120.0)
    p.add_argument("--n-runs", type=int, default=30)
    p.add_argument("--parallel", type=int, default=4)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--python", default=sys.executable)
    p.add_argument("--on-conflict", choices=("skip", "replace"), default="replace")
    p.add_argument("--skip-clone", action="store_true")
    p.add_argument("--skip-clone-if-exists", action="store_true")
    p.add_argument("--clone-only", action="store_true")
    p.add_argument("--skip-promote", action="store_true")
    p.add_argument("--skip-sim-if-manifest-exists", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    # whatif
    p.add_argument("--reuse-baseline-manifest", type=Path, default=None)
    p.add_argument("--baseline-scenario-id", default="")
    p.add_argument("--focus-scopes", default="")
    p.add_argument("--kpi-names", default="")
    p.add_argument("--level", choices=("L1", "L2", "L3"), default="L3")
    # g_star_analysis
    p.add_argument("--g-star-file", type=Path, default=None)
    p.add_argument("--baseline-csv-dir", type=Path, default=None)
    p.add_argument("--anchor-tg", default="")
    args = p.parse_args()

    if args.n_runs < 5:
        print("X --n-runs must be >= 5", file=sys.stderr)
        return 1

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = _resolve_suffix_pattern(args)

    if args.dry_run and not args.skip_clone:
        clone_mod = _load_clone()
        replica_ids = clone_mod.expand_replica_scenario_ids(
            args.template_scenario_id, pattern, args.n_runs,
        )
        print(f"[dry-run clone] would create {len(replica_ids)} replicas")
        for rid in replica_ids[:3]:
            print(f"  {rid}")
        if len(replica_ids) > 3:
            print(f"  ... ({len(replica_ids)} total)")

    clone_manifest = out_dir / "clone_manifest.json"
    if not args.skip_clone and not args.dry_run:
        clone_manifest = _run_clone_step(args, out_dir, pattern)
        if args.clone_only:
            print(f"Clone only — manifest: {clone_manifest}")
            return 0

    if args.clone_only:
        if args.skip_clone:
            print("X --clone-only with --skip-clone does nothing", file=sys.stderr)
            return 1
        if args.dry_run:
            print("[dry-run clone-only] no DB writes")
            return 0
        clone_manifest = _run_clone_step(args, out_dir, pattern)
        print(f"Clone only — manifest: {clone_manifest}")
        return 0

    return _run_batch(args, out_dir, clone_manifest)


if __name__ == "__main__":
    raise SystemExit(main())
