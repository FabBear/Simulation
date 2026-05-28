#!/usr/bin/env python3
"""
Run one FabEnv episode for a FORWARD / WHAT-IF scenario.

Usage (from this directory):
    .venv/bin/python run_sim_forward_once.py --scenario-id FWD_DEMO_180

Status contract (Locked decision §8):
    - load_mes_scenario.py leaves status = DRAFT.
    - Operator/Trigger (ML/Agent) promotes to VALIDATED.
    - This runner ONLY executes scenarios in status='VALIDATED'.
    - On start: VALIDATED -> RUNNING (inside FabEnv._apply_scenario_overrides).
    - On finish: RUNNING -> DONE (FabEnv.finalize_mes_scenario_run()).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _resolve_scenario_or_exit(scenario_id: str):
    from database import SessionLocal
    from models import MesScenario

    db = SessionLocal()
    try:
        sc = db.query(MesScenario).filter(MesScenario.scenario_id == scenario_id).first()
        if sc is None:
            print(f"X scenario not found: {scenario_id}", file=sys.stderr)
            return None
        status = (sc.status or "").upper()
        if status != "VALIDATED":
            print(
                f"X scenario {scenario_id} status={status!r}; runner requires 'VALIDATED'.\n"
                f"   Trigger (ML/Agent/operator) must promote it first.",
                file=sys.stderr,
            )
            return None
        # Snapshot scenario meta so it survives the session close.
        meta = {
            "scenario_id": sc.scenario_id,
            "mode": sc.mode,
            "t0": float(sc.t0_sim_minute or 0.0),
            "horizon": float(sc.horizon_minutes or 0.0),
            "baseline": sc.baseline_scenario_id,
            "use_master_lot_release": bool(sc.use_master_lot_release),
            "description": sc.description,
        }
        return meta
    finally:
        db.close()


def main() -> int:
    p = argparse.ArgumentParser(description="Run one FORWARD / WHAT-IF scenario via FabEnv.")
    p.add_argument("--scenario-id", required=True)
    p.add_argument(
        "--csv-dir",
        default=os.environ.get("SIM_CSV_DIR", str(_ROOT / "sim_csv_out")),
        help="Output directory for CSV logs (default: ./sim_csv_out or SIM_CSV_DIR).",
    )
    p.add_argument(
        "--max-steps",
        type=int,
        default=int(os.environ.get("SIM_CSV_MAX_STEPS", "200000")),
        help="Safety cap on gym.step() iterations (default: 200000).",
    )
    p.add_argument(
        "--rl",
        action="store_true",
        help="Use PPO for dispatch (sets DISPATCH_MODE=rl).",
    )
    p.add_argument(
        "--model",
        default=os.environ.get("PPO_MODEL_PATH", ""),
        help="Path to PPO .zip (required with --rl unless PPO_MODEL_PATH is set).",
    )
    args = p.parse_args()

    meta = _resolve_scenario_or_exit(args.scenario_id)
    if meta is None:
        return 1

    csv_dir = Path(args.csv_dir).resolve()
    csv_dir.mkdir(parents=True, exist_ok=True)
    os.environ["SIM_CSV_DIR"] = str(csv_dir)
    os.environ["SIM_SCENARIO_ID"] = args.scenario_id
    # Scenario horizon overrides any cold-start default.
    os.environ["SIM_END_MINUTES"] = str(meta["horizon"])

    if args.rl:
        os.environ["DISPATCH_MODE"] = "rl"
        if not str(args.model).strip():
            print("X --rl requires --model /path/to/ppo.zip or PPO_MODEL_PATH env", file=sys.stderr)
            return 2

    from fab_env import FabEnv

    print("=" * 64)
    print(f"Scenario     : {meta['scenario_id']}  ({meta['mode']})")
    print(f"T0 (sim min) : {meta['t0']}")
    print(f"Horizon (min): {meta['horizon']}  (SimPy 0..horizon)")
    if meta["baseline"]:
        print(f"Baseline     : {meta['baseline']}")
    if meta["description"]:
        print(f"Description  : {meta['description']}")
    print(f"CSV dir      : {csv_dir}")
    print(f"DISPATCH_MODE: {os.environ.get('DISPATCH_MODE', 'rule')}")
    print("=" * 64)

    env = FabEnv()
    obs, _ = env.reset(options={"scenario_id": args.scenario_id})

    model = None
    if args.rl:
        from stable_baselines3 import PPO

        mp = Path(args.model).expanduser().resolve()
        if not mp.is_file():
            print(f"X Model file not found: {mp}", file=sys.stderr)
            env.finalize_mes_scenario_run()
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
            print(f"  steps={steps} sim_now_rel={env.sim_env.now:.1f} terminated={terminated}")

    env.finalize_mes_scenario_run()

    print("-" * 64)
    print(
        f"Done. gym_steps={steps} sim_now_rel={env.sim_env.now:.1f} "
        f"sim_now_abs={env._sim_now_abs():.1f} terminated={terminated}"
    )
    print(f"Release count (scenario)         : {env._kpi_release_count}")
    print(f"Finished lots                    : {env._kpi_finish_count}")
    print(f"Active lots remaining at horizon : {len(env.active_lots_data)}")
    print(f"Run id (simulation_run)          : {env._csv_run_id}")
    print("Status transition: VALIDATED -> RUNNING -> DONE")
    print("-" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
