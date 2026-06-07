#!/usr/bin/env python3
"""Clone mes_scenario + child rows to N Monte Carlo replicas (same payload, new scenario_id)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database import SessionLocal
from models import (
    MesCqtSnapshot,
    MesForwardInputEvent,
    MesLotReleasePlan,
    MesOperatingEvent,
    MesScenario,
    MesToolQueueSnapshot,
    MesToolSnapshot,
    MesWhatifAction,
    MesWipSnapshot,
)

CHILD_MODELS: tuple[type, ...] = (
    MesWipSnapshot,
    MesToolSnapshot,
    MesToolQueueSnapshot,
    MesLotReleasePlan,
    MesWhatifAction,
    MesForwardInputEvent,
    MesOperatingEvent,
    MesCqtSnapshot,
)


def format_replica_scenario_id(
    source_scenario_id: str,
    suffix_pattern: str,
    run_index: int,
) -> str:
    """Expand suffix pattern for one replica (run_index is 1..N)."""
    return suffix_pattern.format(
        source=source_scenario_id,
        template=source_scenario_id,
        run=run_index,
        run_index=run_index,
    )


def expand_replica_scenario_ids(
    source_scenario_id: str,
    suffix_pattern: str,
    n_runs: int,
) -> list[str]:
    return [
        format_replica_scenario_id(source_scenario_id, suffix_pattern, i)
        for i in range(1, n_runs + 1)
    ]


def _copy_child_rows(db, model: type, source_id: str, replica_id: str) -> int:
    rows = db.query(model).filter(model.scenario_id == source_id).all()
    if not rows:
        return 0
    mapper = model.__mapper__
    count = 0
    for row in rows:
        data: dict[str, Any] = {}
        for col in mapper.column_attrs:
            key = col.key
            if key == "id":
                continue
            data[key] = getattr(row, key)
        data["scenario_id"] = replica_id
        db.add(model(**data))
        count += 1
    return count


def _build_replica_scenario(
    source: MesScenario,
    replica_id: str,
    *,
    source_id: str,
    run_index: int,
    n_runs: int,
    suffix_pattern: str,
) -> MesScenario:
    meta = dict(source.trigger_meta or {})
    meta.update(
        {
            "mc_template_scenario_id": source_id,
            "mc_run_index": run_index,
            "mc_n_runs": n_runs,
            "mc_suffix_pattern": suffix_pattern,
        }
    )
    return MesScenario(
        scenario_id=replica_id,
        description=f"MC replica {run_index}/{n_runs} of {source_id}",
        source_system=source.source_system,
        mes_extract_batch_id=source.mes_extract_batch_id,
        t0_sim_minute=source.t0_sim_minute,
        horizon_minutes=source.horizon_minutes,
        sim_start_calendar=source.sim_start_calendar,
        mode=source.mode,
        master_snapshot_hash=source.master_snapshot_hash,
        baseline_scenario_id=source.baseline_scenario_id,
        trigger_meta=meta,
        use_master_lot_release=source.use_master_lot_release,
        created_by=source.created_by,
        status="DRAFT",
    )


def clone_one_replica(
    db,
    source: MesScenario,
    replica_id: str,
    *,
    run_index: int,
    n_runs: int,
    suffix_pattern: str,
    on_conflict: str,
) -> tuple[str, dict[str, int]]:
    """Return (action, child_counts) where action is created|replaced|skipped."""
    existing = (
        db.query(MesScenario).filter(MesScenario.scenario_id == replica_id).first()
    )
    if existing:
        if on_conflict == "skip":
            return "skipped", {}
        db.delete(existing)
        db.flush()

    replica = _build_replica_scenario(
        source,
        replica_id,
        source_id=source.scenario_id,
        run_index=run_index,
        n_runs=n_runs,
        suffix_pattern=suffix_pattern,
    )
    db.add(replica)
    db.flush()

    counts: dict[str, int] = {}
    for model in CHILD_MODELS:
        n = _copy_child_rows(db, model, source.scenario_id, replica_id)
        if n:
            counts[model.__tablename__] = n

    action = "replaced" if existing else "created"
    return action, counts


def run_clone(
    *,
    source_scenario_id: str,
    suffix_pattern: str,
    n_runs: int,
    on_conflict: str = "replace",
    mode_filter: str | None = None,
    dry_run: bool = False,
    manifest_out: Path | None = None,
) -> dict:
    replica_ids = expand_replica_scenario_ids(source_scenario_id, suffix_pattern, n_runs)
    manifest: dict[str, Any] = {
        "source_scenario_id": source_scenario_id,
        "n_runs": n_runs,
        "suffix_pattern": suffix_pattern,
        "replica_scenario_ids": replica_ids,
        "actions": [],
    }

    if dry_run:
        for rid in replica_ids:
            print(rid)
        if manifest_out:
            manifest_out.parent.mkdir(parents=True, exist_ok=True)
            manifest_out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest

    db = SessionLocal()
    try:
        source = (
            db.query(MesScenario)
            .filter(MesScenario.scenario_id == source_scenario_id)
            .first()
        )
        if not source:
            raise SystemExit(f"X source not found: {source_scenario_id}")

        if mode_filter:
            allowed = {m.strip().upper() for m in mode_filter.split(",") if m.strip()}
            if source.mode.upper() not in allowed:
                raise SystemExit(
                    f"X source mode {source.mode!r} not in mode-filter {sorted(allowed)}"
                )

        for i, replica_id in enumerate(replica_ids, start=1):
            action, counts = clone_one_replica(
                db,
                source,
                replica_id,
                run_index=i,
                n_runs=n_runs,
                suffix_pattern=suffix_pattern,
                on_conflict=on_conflict,
            )
            manifest["actions"].append(
                {"replica_scenario_id": replica_id, "action": action, "child_counts": counts}
            )
            print(f"OK {replica_id} ({action}) {counts or '{}'}")

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    if manifest_out:
        manifest_out.parent.mkdir(parents=True, exist_ok=True)
        manifest_out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def replica_ids_exist(db, replica_ids: list[str]) -> bool:
    if not replica_ids:
        return False
    found = (
        db.query(MesScenario.scenario_id)
        .filter(MesScenario.scenario_id.in_(replica_ids))
        .count()
    )
    return found >= len(replica_ids)


def main() -> int:
    p = argparse.ArgumentParser(description="Clone mes_scenario to N MC replicas")
    p.add_argument("--source-scenario-id", required=True)
    p.add_argument(
        "--suffix-pattern",
        default="{source}_R{run:02d}",
        help="Placeholders: {source}, {template}, {run}, {run_index}",
    )
    p.add_argument("--n-runs", type=int, default=30)
    p.add_argument("--on-conflict", choices=("skip", "replace"), default="replace")
    p.add_argument("--mode-filter", default="", help="e.g. FORWARD,WHATIF")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--manifest-out",
        type=Path,
        default=None,
        help="Write clone_manifest.json path",
    )
    args = p.parse_args()

    if args.n_runs < 1:
        print("X --n-runs must be >= 1", file=sys.stderr)
        return 1

    run_clone(
        source_scenario_id=args.source_scenario_id,
        suffix_pattern=args.suffix_pattern,
        n_runs=args.n_runs,
        on_conflict=args.on_conflict,
        mode_filter=args.mode_filter or None,
        dry_run=args.dry_run,
        manifest_out=args.manifest_out,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
