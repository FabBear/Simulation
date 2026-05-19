#!/usr/bin/env python3
"""
Run one FabEnv episode and append simulation logs to CSV (SIM_CSV_DIR).

Usage (from this directory):
  SIM_CSV_DIR=./sim_csv_out SIM_END_MINUTES=8000 .venv/bin/python run_sim_csv_once.py

Chronological CSV (optional, rewrites files after run):
  .venv/bin/python run_sim_csv_once.py --csv-dir ./sim_csv_out --sort-csv

PPO dispatch:
  DISPATCH_MODE=rl .venv/bin/python run_sim_csv_once.py --rl --model ./logs/ppo_smt_20000_steps.zip ...

Optional args override env defaults.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

# Ensure imports resolve when run as a script
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _float_or_zero(val) -> float:
    if val is None or val == "":
        return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _sort_csv_by_sim_time(fp: Path, time_field: str, tie_fields: tuple[str, ...]) -> None:
    """Rewrite one CSV in-place: data rows sorted by simulation time then tie-breakers (stable KPI order)."""
    if not fp.is_file() or fp.stat().st_size == 0:
        return
    with fp.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    if not fieldnames or not rows:
        return

    def key(row: dict):
        t = _float_or_zero(row.get(time_field))
        rest = tuple(str(row.get(k) or "") for k in tie_fields)
        return (t,) + rest

    rows.sort(key=key)
    with fp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    p = argparse.ArgumentParser(description="Run FabEnv once and write CSV logs.")
    p.add_argument(
        "--csv-dir",
        default=os.environ.get("SIM_CSV_DIR", str(_ROOT / "sim_csv_out")),
        help="Output directory for CSV files (default: ./sim_csv_out or SIM_CSV_DIR)",
    )
    p.add_argument(
        "--end-minutes",
        type=float,
        default=float(os.environ.get("SIM_END_MINUTES", "8000")),
        help="Episode ends when sim_env.now reaches this (default: 8000, or SIM_END_MINUTES)",
    )
    p.add_argument(
        "--max-steps",
        type=int,
        default=int(os.environ.get("SIM_CSV_MAX_STEPS", "200000")),
        help="Safety cap on gym steps (default: 200000)",
    )
    p.add_argument(
        "--rl",
        action="store_true",
        help="Use PPO for dispatch (sets DISPATCH_MODE=rl; FabEnv uses model.predict index into queue)",
    )
    p.add_argument(
        "--model",
        default=os.environ.get("PPO_MODEL_PATH", ""),
        help="Path to PPO .zip (required with --rl unless PPO_MODEL_PATH is set)",
    )
    p.add_argument(
        "--sort-csv",
        action="store_true",
        help=(
            "After the run, rewrite each CSV with data rows sorted by simulation time "
            "(lot_events: event_time; simulation_process: end_time; tool_state: state_change_time). "
            "Large runs load the full file in memory once."
        ),
    )
    args = p.parse_args()

    os.environ["SIM_CSV_DIR"] = str(Path(args.csv_dir).resolve())
    os.environ["SIM_END_MINUTES"] = str(args.end_minutes)

    if args.rl:
        os.environ["DISPATCH_MODE"] = "rl"
        if not str(args.model).strip():
            print("❌ --rl requires --model /path/to/ppo.zip or PPO_MODEL_PATH env", file=sys.stderr)
            return 2

    csv_dir = Path(os.environ["SIM_CSV_DIR"])
    csv_dir.mkdir(parents=True, exist_ok=True)

    from fab_env import FabEnv

    print(f"CSV dir: {csv_dir}")
    print(f"SIM_END_MINUTES: {args.end_minutes}")
    print(f"DISPATCH_MODE: {os.environ.get('DISPATCH_MODE', 'rule')}")
    print("Starting FabEnv reset…")

    env = FabEnv()
    obs, _ = env.reset()

    model = None
    if args.rl:
        from stable_baselines3 import PPO

        mp = Path(args.model).expanduser().resolve()
        if not mp.is_file():
            print(f"❌ Model file not found: {mp}", file=sys.stderr)
            return 2
        model = PPO.load(str(mp))
        print(f"PPO model: {mp}")

    steps = 0
    terminated = False
    while not terminated and steps < args.max_steps:
        if model is not None:
            act, _ = model.predict(obs, deterministic=True)
            act = int(act)
        else:
            act = 0
        obs, _, terminated, _, _ = env.step(act)
        steps += 1
        if steps % 5000 == 0:
            print(f"  steps={steps} sim_now={env.sim_env.now:.1f} terminated={terminated}")

    print(f"Done. gym_steps={steps} sim_now={env.sim_env.now:.1f} terminated={terminated}")
    for name in (
        "simulation_process.csv",
        "lot_events.csv",
        "tool_state.csv",
        "kpi_fab.csv",
        "kpi_process.csv",
        "kpi_toolgroup.csv",
        "kpi_tool.csv",
    ):
        fp = csv_dir / name
        if fp.exists():
            n = sum(1 for _ in fp.open(encoding="utf-8")) - 1
            print(f"  {name}: ~{max(0, n)} data rows (+ header)")
        else:
            print(f"  {name}: (missing — no events of this type)")
    legacy = csv_dir / "kpi_snapshot.csv"
    if legacy.exists():
        n = sum(1 for _ in legacy.open(encoding="utf-8")) - 1
        print(f"  kpi_snapshot.csv (legacy): ~{max(0, n)} data rows (+ header)")

    if args.sort_csv:
        print("Sorting CSV rows by simulation time (--sort-csv)…")
        _sort_csv_by_sim_time(
            csv_dir / "lot_events.csv",
            "event_time",
            ("run_id", "lot_id", "step_seq", "event_type", "tool_id"),
        )
        _sort_csv_by_sim_time(
            csv_dir / "simulation_process.csv",
            "end_time",
            ("run_id", "lot_id", "step_seq", "tool_id"),
        )
        _sort_csv_by_sim_time(
            csv_dir / "tool_state.csv",
            "state_change_time",
            ("run_id", "tool_group", "tool_id", "state", "reason"),
        )
        for kpi_name in ("kpi_fab.csv", "kpi_process.csv", "kpi_toolgroup.csv", "kpi_tool.csv"):
            _sort_csv_by_sim_time(
                csv_dir / kpi_name,
                "snapshot_time",
                ("run_id", "scope", "kpi_name"),
            )
        if legacy.exists():
            _sort_csv_by_sim_time(
                legacy,
                "snapshot_time",
                ("run_id", "level", "scope", "kpi_name"),
            )
        print("  sort: done.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
