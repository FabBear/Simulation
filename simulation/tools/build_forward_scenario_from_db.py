#!/usr/bin/env python3
"""
Build MES FORWARD scenario from PostgreSQL cold-start logs and persist to DB.

Reuses build_scenario_from_inputs() from build_forward_scenario_from_csv.py.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Dict, List

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database import SessionLocal, create_tables  # noqa: E402
from load_mes_scenario import persist_forward_bundle_to_db  # noqa: E402
from models import (  # noqa: E402
    KpiTool,
    LotEventLog,
    LotReleaseLedger,
    SimulationLog,
    ToolStateLog,
)
from tools.build_forward_scenario_from_csv import (  # noqa: E402
    MasterContext,
    ScenarioInputs,
    _apply_ledger_to_traces,
    _collect_arrival_rows,
    _load_kpi_tool_at_from_rows,
    _load_lot_traces_from_rows,
    _load_ltl_lock_from_rows,
    _load_release_ledger_from_rows,
    _load_tool_state_at_from_rows,
    build_scenario_from_inputs,
)


def _ledger_row_from_orm(row: LotReleaseLedger) -> dict:
    return {
        "lot_id": row.lot_id,
        "lot_type": row.lot_type or "",
        "product_name": row.product_name or "",
        "route_name": row.route_name or "",
        "sim_now_min": str(row.sim_now_min),
        "due_date_sim_min": str(row.due_date_sim_min),
        "priority": str(row.priority) if row.priority is not None else "",
        "is_super_hot": "1" if row.is_super_hot else "0",
        "wafers_per_lot": str(row.wafers_per_lot) if row.wafers_per_lot is not None else "",
        "source": row.source or "",
    }


def _lot_event_row_from_orm(row: LotEventLog) -> dict:
    return {
        "lot_id": row.lot_id or "",
        "product": row.product or "",
        "route_id": row.route_id or "",
        "step_seq": "" if row.step_seq is None else str(row.step_seq),
        "tool_group": row.tool_group or "",
        "tool_id": row.tool_id or "",
        "event_type": row.event_type or "",
        "event_time": str(row.event_time) if row.event_time is not None else "",
        "detail_1": row.detail_1 or "",
        "detail_2": row.detail_2 or "",
    }


def _sim_log_row_from_orm(row: SimulationLog) -> dict:
    return {
        "lot_id": row.lot_id or "",
        "step_seq": "" if row.step_seq is None else str(row.step_seq),
        "tool_id": row.tool_id or "",
        "end_time": str(row.end_time) if row.end_time is not None else "",
    }


def _tool_state_row_from_orm(row: ToolStateLog) -> dict:
    return {
        "tool_group": row.tool_group or "",
        "tool_id": row.tool_id or "",
        "state": row.state or "",
        "state_change_time": str(row.state_change_time) if row.state_change_time is not None else "",
        "setup_name": row.setup_name or "",
        "lot_id": row.lot_id or "",
        "reason": row.reason or "",
    }


def _kpi_tool_row_from_orm(row: KpiTool) -> dict:
    return {
        "snapshot_time": str(row.snapshot_time) if row.snapshot_time is not None else "",
        "scope": row.scope or "",
        "kpi_name": row.kpi_name or "",
        "value": str(row.value) if row.value is not None else "",
    }


def load_scenario_inputs_from_db(
    run_id: str,
    t0: float,
    horizon: float,
    db,
) -> ScenarioInputs:
    t_end = t0 + horizon
    ledger_rows = [
        _ledger_row_from_orm(r)
        for r in db.query(LotReleaseLedger).filter(LotReleaseLedger.run_id == run_id).all()
    ]
    ledger = _load_release_ledger_from_rows(ledger_rows)

    lot_rows = [
        _lot_event_row_from_orm(r)
        for r in (
            db.query(LotEventLog)
            .filter(LotEventLog.run_id == run_id, LotEventLog.event_time <= t_end)
            .order_by(LotEventLog.event_time)
            .all()
        )
    ]
    traces = _load_lot_traces_from_rows(lot_rows, t_end, ledger)
    _apply_ledger_to_traces(traces, ledger)

    process_rows = [
        _sim_log_row_from_orm(r)
        for r in (
            db.query(SimulationLog)
            .filter(SimulationLog.run_id == run_id, SimulationLog.end_time <= t0)
            .all()
        )
    ]
    tool_rows = [
        _tool_state_row_from_orm(r)
        for r in (
            db.query(ToolStateLog)
            .filter(ToolStateLog.run_id == run_id, ToolStateLog.state_change_time <= t0)
            .order_by(ToolStateLog.state_change_time)
            .all()
        )
    ]
    kpi_rows = [
        _kpi_tool_row_from_orm(r)
        for r in (
            db.query(KpiTool)
            .filter(KpiTool.run_id == run_id, KpiTool.snapshot_time == float(t0))
            .all()
        )
    ]
    tool_last, run_lot = _load_tool_state_at_from_rows(tool_rows, t0)
    q_len, proc_count = _load_kpi_tool_at_from_rows(kpi_rows, t0)

    return ScenarioInputs(
        ledger=ledger,
        traces=traces,
        ltl_lock=_load_ltl_lock_from_rows(process_rows, t0),
        tool_last=tool_last,
        run_lot=run_lot,
        q_len=q_len,
        proc_count=proc_count,
        arrival_rows=_collect_arrival_rows(lot_rows, t0, t_end),
    )


def _write_csv_bundle(out_dir: Path, built: dict, scenario_id: str, t0: float, horizon: float, run_id: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    def _write(name: str, fieldnames: List[str], rows: List[dict]) -> None:
        path = out_dir / name
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow(r)

    _write(
        "mes_tool_snapshot.csv",
        ["scenario_id", "tool_id", "tool_group", "op_state", "current_setup", "held_lot_id"],
        built["tool_rows"],
    )
    _write(
        "mes_tool_queue_snapshot.csv",
        ["scenario_id", "tool_id", "position", "lot_id", "route_id", "step_seq", "due_date_sim", "priority"],
        built["queue_rows"],
    )
    _write(
        "mes_wip_snapshot.csv",
        [
            "scenario_id", "snapshot_time", "lot_id", "route_id", "current_step_seq", "status",
            "tool_group", "tool_id", "queue_position", "due_date_sim", "priority", "rem_steps",
            "processing_remaining_min", "wafers_per_lot", "product", "is_super_hot",
        ],
        built["wip_rows"],
    )
    _write(
        "mes_lot_release_plan.csv",
        [
            "scenario_id", "product_name", "route_name", "release_time", "lots_count",
            "release_interval", "due_date_sim", "wafers_per_lot", "priority", "is_super_hot",
            "lot_type", "lot_name_prefix", "source_lot_release_id",
        ],
        built["release_rows"],
    )
    (out_dir / "build_confidence.json").write_text(
        json.dumps(built["confidence"], indent=2), encoding="utf-8",
    )
    (out_dir / "mes_scenario.meta.json").write_text(
        json.dumps({
            "scenario_id": scenario_id,
            "mode": "FORWARD",
            "t0_sim_minute": t0,
            "horizon_minutes": horizon,
            "use_master_lot_release": False,
            "source_run_id": run_id,
        }, indent=2),
        encoding="utf-8",
    )


def build_and_persist_from_db(
    run_id: str,
    t0: float,
    horizon: float,
    scenario_id: str,
    *,
    description: str = "Built from DB via build_forward_scenario_from_db.py",
    emit_csv_dir: Path | None = None,
    create_tables_flag: bool = False,
) -> dict:
    if create_tables_flag:
        create_tables()

    master = MasterContext.from_db()
    db = SessionLocal()
    try:
        inputs = load_scenario_inputs_from_db(run_id, t0, horizon, db)
    finally:
        db.close()

    built = build_scenario_from_inputs(master, run_id, t0, horizon, scenario_id, inputs)
    persist_forward_bundle_to_db(
        scenario_id,
        t0,
        horizon,
        description,
        built,
        source_run_id=run_id,
    )
    if emit_csv_dir is not None:
        _write_csv_bundle(emit_csv_dir, built, scenario_id, t0, horizon, run_id)
    return built


def main() -> int:
    p = argparse.ArgumentParser(description="Build FORWARD MES scenario from DB logs and persist.")
    p.add_argument("--run-id", required=True)
    p.add_argument("--t0", type=float, required=True, help="Absolute fab sim minute (snapshot_time).")
    p.add_argument("--horizon", type=float, default=180.0)
    p.add_argument("--scenario-id", required=True)
    p.add_argument("--description", default="Built from DB via build_forward_scenario_from_db.py")
    p.add_argument("--emit-csv", type=Path, default=None, help="Optional debug CSV bundle directory")
    p.add_argument("--create-tables", action="store_true")
    args = p.parse_args()

    try:
        built = build_and_persist_from_db(
            args.run_id.strip(),
            float(args.t0),
            float(args.horizon),
            args.scenario_id,
            description=args.description,
            emit_csv_dir=args.emit_csv,
            create_tables_flag=args.create_tables,
        )
    except Exception as exc:
        print(f"X build_forward_scenario_from_db failed: {exc}", file=sys.stderr)
        print("  Ensure docker Postgres is up, V6 KPI tables exist, and run logs are loaded.", file=sys.stderr)
        return 1

    c = built["confidence"]
    print(f"Persisted scenario {args.scenario_id} to DB")
    print(f"  tools={c['tool_count']} queues={c['queue_count']} wip={c['wip_count']} releases={c['release_count']}")
    if args.emit_csv:
        print(f"  debug CSV bundle -> {args.emit_csv}")
    if c["notes"]:
        for n in c["notes"][:10]:
            print(f"  note: {n}")
    print("Next:")
    print(f"  python tools/promote_scenario_validated.py --scenario-id {args.scenario_id}")
    print(f"  python run_sim_forward_once.py --scenario-id {args.scenario_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
