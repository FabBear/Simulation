#!/usr/bin/env python3
"""
Fill `kpi_whatif_diff` for a WHAT-IF scenario by joining its KPIs against the
baseline FORWARD scenario.

Usage:
    .venv/bin/python tools/compare_whatif.py --whatif-scenario WHATIF_DEMO_180
                                              [--whatif-run-id <uuid>]
                                              [--baseline-run-id <uuid>]
                                              [--purge]

The default behaviour is to pick the latest `simulation_run` per scenario; pass
explicit `--*-run-id` if you need to compare specific runs.  `--purge` removes
existing rows for that whatif run before reinserting.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database import SessionLocal  # noqa: E402
from models import (  # noqa: E402
    MesScenario,
    MesScenarioRun,
    KpiSnapshot,
    KpiWhatifDiff,
)


def _latest_run_id_for_scenario(db, scenario_id: str) -> Optional[str]:
    """Return the most recent simulation_run linked to this scenario via mes_scenario_run."""
    row = (
        db.query(MesScenarioRun)
        .filter(MesScenarioRun.scenario_id == scenario_id)
        .order_by(MesScenarioRun.started_at.desc())
        .first()
    )
    return row.simulation_run_id if row else None


def _load_kpi_map(db, run_id: str) -> dict:
    """Return { (level, scope, kpi_name, snapshot_time) -> value } for a run."""
    rows = db.query(KpiSnapshot).filter(KpiSnapshot.run_id == run_id).all()
    out = {}
    for r in rows:
        key = (
            str(r.level or ""),
            str(r.scope or ""),
            str(r.kpi_name or ""),
            float(r.snapshot_time or 0.0),
        )
        out[key] = float(r.value) if r.value is not None else None
    return out


def compute_diff(db, whatif_scenario_id: str,
                 whatif_run_id: Optional[str] = None,
                 baseline_run_id: Optional[str] = None,
                 purge: bool = False) -> int:
    sc = db.query(MesScenario).filter(MesScenario.scenario_id == whatif_scenario_id).first()
    if sc is None:
        raise SystemExit(f"scenario not found: {whatif_scenario_id}")
    if (sc.mode or "").upper() != "WHATIF":
        raise SystemExit(f"scenario {whatif_scenario_id} is not WHATIF (mode={sc.mode})")
    if not sc.baseline_scenario_id:
        raise SystemExit(f"scenario {whatif_scenario_id} has no baseline_scenario_id; cannot diff")
    baseline_scenario_id = sc.baseline_scenario_id

    wf_run = whatif_run_id or _latest_run_id_for_scenario(db, whatif_scenario_id)
    bl_run = baseline_run_id or _latest_run_id_for_scenario(db, baseline_scenario_id)
    if not wf_run:
        raise SystemExit(f"no simulation_run found for whatif scenario {whatif_scenario_id}")
    if not bl_run:
        raise SystemExit(f"no simulation_run found for baseline scenario {baseline_scenario_id}")

    if purge:
        db.query(KpiWhatifDiff).filter(KpiWhatifDiff.whatif_run_id == wf_run).delete()
        db.commit()

    bl_kpis = _load_kpi_map(db, bl_run)
    wf_kpis = _load_kpi_map(db, wf_run)
    keys = set(bl_kpis.keys()) | set(wf_kpis.keys())

    n = 0
    for key in sorted(keys):
        level, scope, kpi_name, snap_t = key
        b = bl_kpis.get(key)
        w = wf_kpis.get(key)
        delta = None
        if b is not None and w is not None:
            delta = w - b
        db.add(KpiWhatifDiff(
            whatif_scenario_id=whatif_scenario_id,
            baseline_scenario_id=baseline_scenario_id,
            baseline_run_id=bl_run,
            whatif_run_id=wf_run,
            level=level, scope=scope, kpi_name=kpi_name,
            snapshot_time=float(snap_t),
            baseline_value=b, whatif_value=w, delta=delta,
        ))
        n += 1
    db.commit()
    return n


def main() -> int:
    p = argparse.ArgumentParser(description="Fill kpi_whatif_diff for a WHAT-IF scenario.")
    p.add_argument("--whatif-scenario", required=True)
    p.add_argument("--whatif-run-id", default=None,
                   help="Specific simulation_run.run_id for the WHATIF run.")
    p.add_argument("--baseline-run-id", default=None,
                   help="Specific simulation_run.run_id for the baseline FORWARD run.")
    p.add_argument("--purge", action="store_true",
                   help="Delete existing kpi_whatif_diff rows for this WHATIF run first.")
    args = p.parse_args()

    db = SessionLocal()
    try:
        n = compute_diff(
            db,
            whatif_scenario_id=args.whatif_scenario,
            whatif_run_id=args.whatif_run_id,
            baseline_run_id=args.baseline_run_id,
            purge=args.purge,
        )
        print(f"Inserted {n} kpi_whatif_diff rows for {args.whatif_scenario}.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
