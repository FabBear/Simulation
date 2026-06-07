#!/usr/bin/env python3
"""Orchestrate N sim runs + stat pipelines A/B (Locked #10)."""
from __future__ import annotations

import argparse
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from stats.common import (
    PairedRunMeta,
    RunMeta,
    build_paired_manifest_from_runs_manifest,
    iso_now,
    list_run_dirs,
    load_baseline_manifest_for_reuse,
    load_g_star,
    merge_handoff,
    write_json,
    write_paired_manifest,
    write_runs_manifest,
)
from stats.g_star_analysis import (
    GStarAnalysisConfig,
    run_g_star_analysis,
    write_g_star_analysis_outputs,
)
from stats.whatif_effect import WhatifEffectConfig, run_whatif_paired_analysis, write_whatif_outputs

_RUNNER = _ROOT / "run_sim_forward_once.py"
_PROMOTER = Path(__file__).resolve().parent / "promote_scenario_validated.py"
_STAT_A = Path(__file__).resolve().parent / "stat_g_star_analysis_report.py"
_STAT_B = Path(__file__).resolve().parent / "stat_whatif_paired_report.py"


def _scenario_id(
    pattern: str,
    run_index: int,
    fallback: str,
    *,
    template: str = "",
) -> str:
    if "{" in pattern:
        tpl = template or fallback
        return pattern.format(
            run=run_index,
            run_index=run_index,
            source=tpl,
            template=tpl,
        )
    return fallback


def _scenario_ids_for_batch(
    pattern: str,
    fallback: str,
    indices,
    *,
    template: str = "",
) -> list[str]:
    if not pattern:
        return [fallback] if fallback else []
    out: list[str] = []
    seen: set[str] = set()
    for i in indices:
        sid = _scenario_id(pattern, i, fallback, template=template)
        if sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


def _effective_parallel(args: argparse.Namespace, scenario_ids: list[str]) -> int:
    if len(scenario_ids) == 1 and args.parallel > 1:
        print(
            f"WARN single scenario_id {scenario_ids[0]!r}: "
            f"forcing parallel=1 (use suffix-pattern for MC parallel)",
            file=sys.stderr,
        )
        return 1
    return args.parallel


def _monte_carlo_block(
    args: argparse.Namespace,
    *,
    effective_parallel: int,
    clone_manifest: str | None = None,
) -> dict | None:
    template = (getattr(args, "template_scenario_id", None) or "").strip()
    pattern = (
        args.whatif_suffix_pattern
        or args.scenario_suffix_pattern
        or ""
    ).strip()
    if not template and not pattern and not clone_manifest:
        return None
    return {
        "n_runs": args.n_runs,
        "template_scenario_id": template or None,
        "suffix_pattern": pattern or None,
        "execution_mode": "parallel" if effective_parallel > 1 else "serial",
        "clone_manifest": clone_manifest,
    }


def _promote_scenario(python: str, scenario_id: str, *, dry_run: bool) -> int:
    cmd = [python, str(_PROMOTER), "--scenario-id", scenario_id]
    if dry_run:
        print("[dry-run promote]", " ".join(cmd))
        return 0
    proc = subprocess.run(cmd, cwd=str(_ROOT), capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stderr or proc.stdout, file=sys.stderr)
    else:
        out = (proc.stdout or "").strip()
        if out:
            print(out)
    return proc.returncode


def _promote_before_batch(args: argparse.Namespace, scenario_ids: list[str]) -> None:
    if args.skip_promote or not scenario_ids:
        return
    for sid in scenario_ids:
        code = _promote_scenario(args.python, sid, dry_run=args.dry_run)
        if code != 0 and not args.dry_run:
            print(f"X promote failed: {sid}", file=sys.stderr)
            raise SystemExit(1)


def _failed_runs(runs: list[RunMeta]) -> list[RunMeta]:
    return [r for r in runs if (r.status or "") != "ok"]


def _failed_whatif_rows(rows: list[dict]) -> list[dict]:
    return [r for r in rows if (r.get("status") or "") != "ok"]


def _run_one_sim(
    *,
    scenario_id: str,
    seed: int,
    csv_dir: Path,
    python: str,
    dry_run: bool,
) -> tuple[int, str, str]:
    csv_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        python,
        str(_RUNNER),
        "--scenario-id",
        scenario_id,
        "--seed",
        str(seed),
        "--csv-dir",
        str(csv_dir),
    ]
    if dry_run:
        print(" ".join(cmd))
        return 0, "", scenario_id
    proc = subprocess.run(cmd, cwd=str(_ROOT), capture_output=True, text=True)
    run_id = ""
    for line in (proc.stdout or "").splitlines():
        if "Run id" in line and ":" in line:
            run_id = line.split(":", 1)[-1].strip()
    if proc.returncode != 0:
        print(proc.stderr or proc.stdout, file=sys.stderr)
    return proc.returncode, run_id, scenario_id


def _count_ok_manifest(path: Path) -> int:
    if not path.is_file():
        return 0
    return sum(1 for r in list_run_dirs(path) if (r.status or "ok") == "ok")


def _run_baseline_batch(
    args: argparse.Namespace,
    out_dir: Path,
    *,
    skip_if_exists: bool,
) -> list[RunMeta]:
    manifest_path = out_dir / "runs_manifest.csv"
    if skip_if_exists and _count_ok_manifest(manifest_path) >= args.n_runs:
        print(f"Skip baseline sim: {manifest_path} has {args.n_runs} ok rows")
        return load_baseline_manifest_for_reuse(manifest_path, args.n_runs)

    pattern = args.scenario_suffix_pattern or ""
    fallback = args.baseline_scenario_id
    template = (getattr(args, "template_scenario_id", None) or fallback or "").strip()
    sids = _scenario_ids_for_batch(
        pattern, fallback, range(1, args.n_runs + 1), template=template,
    )
    multi_id = len(sids) > 1
    if multi_id:
        _promote_before_batch(args, sids)
    parallel = _effective_parallel(args, sids)
    runs: list[RunMeta] = []

    def job(i: int) -> RunMeta:
        seed = i
        sid = _scenario_id(pattern, i, fallback, template=template) if pattern else fallback
        if not multi_id and not args.skip_promote:
            code = _promote_scenario(args.python, sid, dry_run=args.dry_run)
            if code != 0 and not args.dry_run:
                return RunMeta(
                    run_index=i,
                    seed=seed,
                    csv_dir=out_dir / "runs" / f"run_{i:02d}",
                    run_id="",
                    scenario_id=sid,
                    status="failed",
                )
        run_dir = out_dir / "runs" / f"run_{i:02d}"
        code, run_id, sid_used = _run_one_sim(
            scenario_id=sid,
            seed=seed,
            csv_dir=run_dir,
            python=args.python,
            dry_run=args.dry_run,
        )
        from stats.common import _first_run_id
        rid = run_id or _first_run_id(run_dir)
        return RunMeta(
            run_index=i,
            seed=seed,
            csv_dir=run_dir,
            run_id=rid,
            scenario_id=sid_used,
            status="ok" if code == 0 else "failed",
        )

    if args.dry_run:
        for i in range(1, args.n_runs + 1):
            runs.append(job(i))
    else:
        with ThreadPoolExecutor(max_workers=parallel) as ex:
            futs = {ex.submit(job, i): i for i in range(1, args.n_runs + 1)}
            for fut in as_completed(futs):
                runs.append(fut.result())
        runs.sort(key=lambda r: r.run_index)

    if not args.dry_run:
        write_runs_manifest(manifest_path, runs)
    return runs


def _run_whatif_batch(
    args: argparse.Namespace,
    out_dir: Path,
    baselines: list[RunMeta],
    *,
    skip_if_exists: bool,
) -> tuple[list[PairedRunMeta], list[dict]]:
    paired_path = out_dir / "paired_manifest.csv"
    if skip_if_exists and paired_path.is_file():
        from stats.common import list_paired_runs
        pairs = list_paired_runs(paired_path)
        ok = [p for p in pairs if p.whatif_csv_dir.is_dir()]
        if len(ok) >= args.n_runs:
            print(f"Skip whatif sim: {paired_path} has {len(ok)} rows")
            return ok[: args.n_runs], []

    pattern = args.whatif_suffix_pattern or ""
    fallback = args.whatif_scenario_id
    template = (getattr(args, "template_scenario_id", None) or fallback or "").strip()
    sids = _scenario_ids_for_batch(
        pattern,
        fallback,
        [b.run_index for b in baselines],
        template=template,
    )
    multi_id = len(sids) > 1
    if multi_id:
        _promote_before_batch(args, sids)
    parallel = _effective_parallel(args, sids)
    whatif_rows: list[dict] = []

    def job(base: RunMeta) -> dict:
        i = base.run_index
        sid = _scenario_id(pattern, i, fallback, template=template) if pattern else fallback
        if not multi_id and not args.skip_promote:
            code = _promote_scenario(args.python, sid, dry_run=args.dry_run)
            if code != 0 and not args.dry_run:
                return {
                    "run_index": i,
                    "seed": base.seed,
                    "csv_dir": str(out_dir / "whatif_runs" / f"run_{i:02d}"),
                    "run_id": "",
                    "scenario_id": sid,
                    "status": "failed",
                }
        run_dir = out_dir / "whatif_runs" / f"run_{i:02d}"
        code, run_id, sid_used = _run_one_sim(
            scenario_id=sid,
            seed=base.seed,
            csv_dir=run_dir,
            python=args.python,
            dry_run=args.dry_run,
        )
        from stats.common import _first_run_id
        return {
            "run_index": i,
            "seed": base.seed,
            "csv_dir": str(run_dir),
            "run_id": run_id or _first_run_id(run_dir),
            "scenario_id": sid_used,
            "status": "ok" if code == 0 else "failed",
        }

    if args.dry_run:
        whatif_rows = [job(b) for b in baselines]
    else:
        with ThreadPoolExecutor(max_workers=parallel) as ex:
            futs = [ex.submit(job, b) for b in baselines]
            whatif_rows = [f.result() for f in as_completed(futs)]
        whatif_rows.sort(key=lambda r: int(r["run_index"]))

    pairs = build_paired_manifest_from_runs_manifest(
        out_dir / "runs_manifest.csv",
        whatif_rows,
    )
    if not args.dry_run:
        write_paired_manifest(paired_path, pairs)
    return pairs, whatif_rows


def _g_star_analysis_handoff(args, out_dir: Path, runs: list[RunMeta]) -> dict:
    g_star = load_g_star(args.g_star_file)
    anchor = args.anchor_tg.strip() or None
    kpis = tuple(
        k.strip()
        for k in (args.kpis or "q_time_min,wait_ratio,wip,available_tool_ratio,utilization_avg").split(",")
        if k.strip()
    )
    cfg = GStarAnalysisConfig(
        t0=args.t0,
        horizon=args.horizon,
        alpha=args.alpha,
        independence_alpha=getattr(args, "independence_alpha", 0.01),
        lb_lags=getattr(args, "lb_lags", 10),
        n_diff=getattr(args, "n_diff", 30),
        multipletest=getattr(args, "multipletest", "fdr_bh"),
        kpis=kpis,
    )
    baseline_dir = Path(getattr(args, "baseline_csv_dir") or args.out_dir)
    summary = run_g_star_analysis(
        runs, g_star,
        baseline_csv_dir=baseline_dir,
        anchor_tg=anchor,
        config=cfg,
    )
    return write_g_star_analysis_outputs(
        out_dir,
        summary,
        cfg=cfg,
        g_star=g_star,
        anchor_tg=anchor or (sorted(g_star)[0] if g_star else ""),
        n_runs=len(runs),
        baseline_csv_dir=str(baseline_dir),
    )


def _whatif_handoff(args, out_dir: Path, pairs: list[PairedRunMeta]) -> dict:
    focus = [x.strip() for x in (args.focus_scopes or "").split(",") if x.strip()] or None
    kpi = [x.strip() for x in (args.kpi_names or "").split(",") if x.strip()] or None
    cfg = WhatifEffectConfig(
        t0=args.t0,
        horizon=args.horizon,
        level=args.level,
        kpi_names=kpi,
        focus_scopes=focus,
    )
    summary = run_whatif_paired_analysis(
        pairs,
        config=cfg,
        baseline_scenario_id=args.baseline_scenario_id,
        whatif_scenario_id=args.whatif_scenario_id,
    )
    return write_whatif_outputs(
        out_dir,
        summary,
        cfg=cfg,
        baseline_scenario_id=args.baseline_scenario_id,
        whatif_scenario_id=args.whatif_scenario_id,
        paired_n=len(pairs),
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Stat batch: sim + g_star_analysis / whatif")
    p.add_argument(
        "--mode",
        choices=("g_star_analysis", "whatif", "both"),
        required=True,
        help="Track A = g_star_analysis (root_cause Agent).",
    )
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--t0", type=float, required=True)
    p.add_argument("--horizon", type=float, default=120.0)
    p.add_argument("--n-runs", type=int, default=30)
    p.add_argument("--parallel", type=int, default=4)
    p.add_argument("--python", default=sys.executable)
    p.add_argument("--baseline-scenario-id", default="")
    p.add_argument("--whatif-scenario-id", default="")
    p.add_argument("--scenario-suffix-pattern", default="")
    p.add_argument("--whatif-suffix-pattern", default="")
    p.add_argument("--g-star-file", type=Path, default=None)
    p.add_argument("--anchor-tg", default="")
    p.add_argument("--reuse-baseline-manifest", type=Path, default=None)
    p.add_argument("--alpha", type=float, default=0.05)
    p.add_argument("--baseline-csv-dir", type=Path, default=None,
                   help="Cold-start history CSV dir for baseline diffs (g_star_analysis).")
    p.add_argument("--independence-alpha", type=float, default=0.01)
    p.add_argument("--lb-lags", type=int, default=10)
    p.add_argument("--n-diff", type=int, default=30)
    p.add_argument("--multipletest", default="fdr_bh",
                   choices=("fdr_bh", "bonferroni", "none"))
    p.add_argument("--kpis", default="q_time_min,wait_ratio,wip,available_tool_ratio,utilization_avg")
    p.add_argument("--focus-scopes", default="")
    p.add_argument("--kpi-names", default="")
    p.add_argument("--level", choices=("L1", "L2", "L3"), default="L3")
    p.add_argument("--skip-sim-if-manifest-exists", action="store_true")
    p.add_argument(
        "--skip-promote",
        action="store_true",
        help="Skip promote_scenario_validated (advanced; sim fails if status!=VALIDATED)",
    )
    p.add_argument("--write-combined-handoff", action="store_true")
    p.add_argument(
        "--template-scenario-id",
        default="",
        help="MC template scenario_id for handoff monte_carlo metadata",
    )
    p.add_argument(
        "--clone-manifest",
        default="",
        help="Path to clone_manifest.json (handoff monte_carlo.clone_manifest)",
    )
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if args.n_runs < 5:
        print("X --n-runs must be >= 5", file=sys.stderr)
        return 1

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    mode = args.mode

    if mode == "whatif" and not args.reuse_baseline_manifest:
        print(
            "X --mode whatif requires --reuse-baseline-manifest (Track A runs_manifest.csv)",
            file=sys.stderr,
        )
        return 1

    gsa_block = None
    whatif_block = None
    g_star_list: list[str] | None = None
    mc_effective_parallel = args.parallel

    runs: list[RunMeta] = []
    pairs: list[PairedRunMeta] = []

    if mode in ("g_star_analysis", "both"):
        if not args.g_star_file:
            print("X --g-star-file required for g_star_analysis", file=sys.stderr)
            return 1
        if not args.baseline_scenario_id and not args.scenario_suffix_pattern:
            print("X --baseline-scenario-id or --scenario-suffix-pattern required", file=sys.stderr)
            return 1
        runs = _run_baseline_batch(
            args, out_dir, skip_if_exists=args.skip_sim_if_manifest_exists,
        )
        if args.dry_run:
            return 0
        failed = _failed_runs(runs)
        if failed:
            print(
                f"X baseline sim: {len(failed)}/{len(runs)} failed — skipping stat handoff",
                file=sys.stderr,
            )
            return 1
        gsa_block = _g_star_analysis_handoff(args, out_dir, runs)
        g_star_list = sorted(load_g_star(args.g_star_file))
        pattern = args.scenario_suffix_pattern or ""
        baseline_sids = _scenario_ids_for_batch(
            pattern,
            args.baseline_scenario_id,
            range(1, args.n_runs + 1),
            template=(args.template_scenario_id or args.baseline_scenario_id or "").strip(),
        )
        mc_effective_parallel = _effective_parallel(args, baseline_sids)
        mc_block = _monte_carlo_block(
            args,
            effective_parallel=mc_effective_parallel,
            clone_manifest=args.clone_manifest or None,
        )
        payload_a = {
            "version": "1.0",
            "pipeline": "g_star_analysis",
            "target_agent": "root_cause",
            "generated_at": iso_now(),
            "t0_sim_minute": args.t0,
            "horizon_minutes": args.horizon,
            "n_runs": len(runs),
            "label_rule": "assign_bottleneck_labels / REPORT §4.3",
            "g_star_toolgroups": g_star_list,
            "runs_manifest": "runs_manifest.csv",
            "g_star_analysis": gsa_block,
            "agent_notes": [
                "G* = ML alarm at T0 predicting bottleneck at T0+horizon.",
                "Analysis pool = G* only; non-G* rows in summary are status=not_in_g_star (reference).",
                "Handoff includes ALL G* x KPI evidence (t_p_adj, delta_mean) regardless of kpi_significant.",
                "Primary Agent input: g_star_analysis.g_star_kpi_evidence (inline JSON stat rows).",
                "p-values BH-FDR corrected within G* x KPI only.",
            ],
        }
        if mc_block:
            payload_a["monte_carlo"] = mc_block
        write_json(out_dir / "agent_handoff_g_star_analysis.json", payload_a)

    if mode in ("whatif", "both"):
        if not args.whatif_scenario_id and not args.whatif_suffix_pattern:
            print("X --whatif-scenario-id or --whatif-suffix-pattern required", file=sys.stderr)
            return 1
        if mode == "whatif":
            baselines = load_baseline_manifest_for_reuse(
                args.reuse_baseline_manifest.resolve(),
                args.n_runs,
            )
            manifest_copy = out_dir / "runs_manifest.csv"
            if not manifest_copy.is_file():
                write_runs_manifest(manifest_copy, baselines)
        else:
            baselines = runs
            if not baselines:
                baselines = load_baseline_manifest_for_reuse(
                    out_dir / "runs_manifest.csv", args.n_runs,
                )

        pairs, whatif_rows = _run_whatif_batch(
            args, out_dir, baselines,
            skip_if_exists=args.skip_sim_if_manifest_exists,
        )
        if args.dry_run:
            return 0
        failed_w = _failed_whatif_rows(whatif_rows)
        if failed_w:
            print(
                f"X whatif sim: {len(failed_w)}/{len(whatif_rows)} failed — skipping stat handoff",
                file=sys.stderr,
            )
            return 1
        whatif_block = _whatif_handoff(args, out_dir, pairs)
        wf_pattern = args.whatif_suffix_pattern or ""
        whatif_sids = _scenario_ids_for_batch(
            wf_pattern,
            args.whatif_scenario_id,
            range(1, args.n_runs + 1),
            template=(args.template_scenario_id or args.whatif_scenario_id or "").strip(),
        )
        mc_effective_parallel = _effective_parallel(args, whatif_sids)
        mc_block = _monte_carlo_block(
            args,
            effective_parallel=mc_effective_parallel,
            clone_manifest=args.clone_manifest or None,
        )
        payload_b = {
            "version": "1.0",
            "pipeline": "whatif",
            "target_agent": "whatif_verification",
            "generated_at": iso_now(),
            "t0_sim_minute": args.t0,
            "horizon_minutes": args.horizon,
            "paired_n": len(pairs),
            "paired_manifest": "paired_manifest.csv",
            "baseline_reused_from": (
                Path(args.reuse_baseline_manifest).name
                if args.reuse_baseline_manifest
                else "runs_manifest.csv"
            ),
            "whatif": whatif_block,
            "agent_notes": [
                "Paired t on D_i = whatif_i - baseline_i; same seed as runs_manifest.",
                "Primary Agent input: whatif.whatif_paired_results (inline JSON stat rows).",
                "Does not consume g_star_kpi_evidence.",
            ],
        }
        if mc_block:
            payload_b["monte_carlo"] = mc_block
        write_json(out_dir / "agent_handoff_whatif.json", payload_b)

    if args.write_combined_handoff or (mode == "both" and not args.dry_run):
        combined = merge_handoff(
            gsa_block,
            whatif_block,
            t0=args.t0,
            horizon=args.horizon,
            n_runs=args.n_runs,
            g_star=g_star_list,
        )
        write_json(out_dir / "agent_handoff.json", combined)

    print(f"Done mode={mode} out_dir={out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
