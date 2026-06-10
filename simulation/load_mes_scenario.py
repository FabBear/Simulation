#!/usr/bin/env python3
"""Load MES FORWARD / WHAT-IF scenario bundles into Postgres."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database import SessionLocal, create_tables
from models import (
    MesScenario,
    MesWipSnapshot,
    MesToolSnapshot,
    MesToolQueueSnapshot,
    MesLotReleasePlan,
    MesCqtSnapshot,
    MesForwardInputEvent,
    MesWhatifAction,
    MesOperatingEvent,
    ProcessStep,
    ToolGroup,
)

# SSOT: docs/TRIGGER_CONTRACT.md § mes_wip_snapshot.status vocabulary
MES_WIP_STATUS_CANONICAL = frozenset({
    "QUEUING",
    "PROCESSING",
    "WAIT_TRANSPORT",
    "HOLD",
    "WAIT_BATCH",
})

# Snapshot V2 / Agent internal aliases → MES DB enum (normalized on load).
MES_WIP_STATUS_ALIASES: dict[str, str] = {
    "QUEUE": "QUEUING",
    "TRANSPORT": "WAIT_TRANSPORT",
}


def normalize_mes_wip_status(raw: str) -> str:
    """Map aliases to MES vocabulary; reject unknown values before DB insert."""
    key = (raw or "").strip().upper()
    if not key:
        raise ValueError("mes_wip_snapshot.status is empty")
    canonical = MES_WIP_STATUS_ALIASES.get(key, key)
    if canonical not in MES_WIP_STATUS_CANONICAL:
        allowed = ", ".join(sorted(MES_WIP_STATUS_CANONICAL))
        raise ValueError(
            f"mes_wip_snapshot.status {raw!r} → {canonical!r} not allowed; "
            f"allowed: {allowed}; aliases: QUEUE→QUEUING, TRANSPORT→WAIT_TRANSPORT"
        )
    return canonical


def _float(v):
    if v is None or str(v).strip() == "":
        return None
    return float(v)


def _int(v):
    if v is None or str(v).strip() == "":
        return None
    return int(float(v))


def _bool(v):
    return str(v or "").strip().lower() in ("1", "true", "yes", "y")


def _row_hash(row: dict) -> str:
    payload = "|".join(f"{k}={row.get(k) or ''}" for k in sorted(row.keys()))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _load_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return [r for r in csv.DictReader(f) if any(str(v or "").strip() for v in r.values())]


def _upsert_scenario(db, args) -> MesScenario:
    sc = db.query(MesScenario).filter(MesScenario.scenario_id == args.scenario_id).first()
    prev_status = sc.status if sc else None
    trigger = None
    if args.trigger_meta:
        meta_str = args.trigger_meta.strip()
        if meta_str.startswith(("{", "[")):
            trigger = json.loads(meta_str)
        else:
            try:
                _is_file = Path(meta_str).is_file()
            except OSError:
                _is_file = False
            trigger = json.loads(Path(meta_str).read_text(encoding="utf-8")) if _is_file else json.loads(meta_str)
    if not sc:
        sc = MesScenario(scenario_id=args.scenario_id)
        db.add(sc)
    sc.description = args.description
    sc.t0_sim_minute = float(args.t0)
    sc.horizon_minutes = float(args.horizon)
    sc.mode = args.mode.upper().replace("-", "")
    if sc.mode == "WHAT-IF":
        sc.mode = "WHATIF"
    sc.baseline_scenario_id = args.baseline or None
    sc.use_master_lot_release = bool(args.use_master_lot_release)
    sc.trigger_meta = trigger
    if getattr(args, "force_draft", False) or prev_status in (None, "DRAFT"):
        sc.status = "DRAFT"
    else:
        sc.status = prev_status
    db.flush()
    return sc


def _load_table_rows(db, scenario_id: str, table: str, path: Path, loader):
    rows = _load_csv(path)
    if not rows:
        return 0
    loader(db, scenario_id, rows)
    return len(rows)


def _load_wip(db, scenario_id, rows):
    db.query(MesWipSnapshot).filter(MesWipSnapshot.scenario_id == scenario_id).delete()
    for row in rows:
        db.add(MesWipSnapshot(
            scenario_id=scenario_id,
            snapshot_time=float(row["snapshot_time"]),
            lot_id=row["lot_id"].strip(),
            route_id=row["route_id"].strip(),
            current_step_seq=int(row["current_step_seq"]),
            status=normalize_mes_wip_status(row["status"]),
            tool_group=(row.get("tool_group") or "").strip() or None,
            tool_id=(row.get("tool_id") or "").strip() or None,
            queue_position=_int(row.get("queue_position")),
            due_date_sim=_float(row.get("due_date_sim")),
            priority=_int(row.get("priority")),
            rem_steps=_int(row.get("rem_steps")),
            processing_remaining_min=_float(row.get("processing_remaining_min")),
            wafers_per_lot=_int(row.get("wafers_per_lot")),
            product=(row.get("product") or "").strip() or None,
            is_super_hot=_bool(row.get("is_super_hot")),
        ))


def _load_tools(db, scenario_id, rows):
    db.query(MesToolSnapshot).filter(MesToolSnapshot.scenario_id == scenario_id).delete()
    for row in rows:
        db.add(MesToolSnapshot(
            scenario_id=scenario_id,
            tool_id=row["tool_id"].strip(),
            tool_group=row["tool_group"].strip(),
            op_state=row["op_state"].strip(),
            current_setup=(row.get("current_setup") or "").strip() or None,
            held_lot_id=(row.get("held_lot_id") or "").strip() or None,
        ))


def _load_queues(db, scenario_id, rows):
    db.query(MesToolQueueSnapshot).filter(MesToolQueueSnapshot.scenario_id == scenario_id).delete()
    for row in rows:
        db.add(MesToolQueueSnapshot(
            scenario_id=scenario_id,
            tool_id=row["tool_id"].strip(),
            position=int(row["position"]),
            lot_id=row["lot_id"].strip(),
            route_id=(row.get("route_id") or "").strip() or None,
            step_seq=_int(row.get("step_seq")),
            due_date_sim=_float(row.get("due_date_sim")),
            priority=_int(row.get("priority")),
        ))


def _load_releases(db, scenario_id, rows):
    db.query(MesLotReleasePlan).filter(MesLotReleasePlan.scenario_id == scenario_id).delete()
    for i, row in enumerate(rows, start=2):
        db.add(MesLotReleasePlan(
            scenario_id=scenario_id,
            source_lot_release_id=_int(row.get("source_lot_release_id")),
            product_name=row["product_name"].strip(),
            route_name=row["route_name"].strip(),
            release_time=float(row["release_time"]),
            lots_count=_int(row.get("lots_count")) or 1,
            release_interval=_float(row.get("release_interval")),
            lot_name_prefix=(row.get("lot_name_prefix") or "").strip() or None,
            lot_type=(row.get("lot_type") or "").strip() or None,
            priority=_int(row.get("priority")),
            due_date_sim=_float(row.get("due_date_sim")),
            wafers_per_lot=_int(row.get("wafers_per_lot")),
            is_super_hot=_bool(row.get("is_super_hot")),
            mes_row_hash=(row.get("mes_row_hash") or "").strip() or _row_hash(row),
            source_line_no=i,
        ))


def _load_forward_events(db, scenario_id, rows):
    db.query(MesForwardInputEvent).filter(MesForwardInputEvent.scenario_id == scenario_id).delete()
    for i, row in enumerate(rows, start=2):
        db.add(MesForwardInputEvent(
            scenario_id=scenario_id,
            seq=_int(row.get("seq")) or 0,
            lot_id=row["lot_id"].strip(),
            route_id=row["route_id"].strip(),
            step_seq=_int(row.get("step_seq")),
            event_kind=row["event_kind"].strip().upper(),
            scheduled_time=float(row["scheduled_time"]),
            tool_group=(row.get("tool_group") or "").strip() or None,
            tool_id=(row.get("tool_id") or "").strip() or None,
            priority=_int(row.get("priority")),
            due_date_sim=_float(row.get("due_date_sim")),
            mes_row_hash=(row.get("mes_row_hash") or "").strip() or _row_hash(row),
            source_line_no=i,
            note=(row.get("note") or "").strip() or None,
        ))


def _load_whatif(db, scenario_id, rows):
    db.query(MesWhatifAction).filter(MesWhatifAction.scenario_id == scenario_id).delete()
    for row in rows:
        payload = row.get("payload_json")
        if payload and isinstance(payload, str) and payload.strip():
            payload = json.loads(payload)
        else:
            payload = None
        db.add(MesWhatifAction(
            scenario_id=scenario_id,
            seq=_int(row.get("seq")) or 0,
            action_kind=row["action_kind"].strip().upper(),
            effective_time=float(row["effective_time"]),
            lot_id=(row.get("lot_id") or "").strip() or None,
            route_id=(row.get("route_id") or "").strip() or None,
            step_seq=_int(row.get("step_seq")),
            tool_group=(row.get("tool_group") or "").strip() or None,
            tool_id=(row.get("tool_id") or "").strip() or None,
            payload_json=payload,
            source=(row.get("source") or "AGENT").strip(),
            mes_row_hash=(row.get("mes_row_hash") or "").strip() or _row_hash(row),
        ))


def _audit_fab_env_compat(db, scenario_id: str, skipped_tables: list[str] | None = None) -> list[str]:
    """Runtime checks for load_mes_scenario ↔ fab_env inject conflicts (debug audit)."""
    conflicts: list[str] = []
    sc = db.query(MesScenario).filter(MesScenario.scenario_id == scenario_id).first()
    if not sc:
        return conflicts

    t0 = float(sc.t0_sim_minute)
    t_end = t0 + float(sc.horizon_minutes)
    wip_rows = db.query(MesWipSnapshot).filter(MesWipSnapshot.scenario_id == scenario_id).all()
    queue_rows = db.query(MesToolQueueSnapshot).filter(MesToolQueueSnapshot.scenario_id == scenario_id).all()
    tool_rows = db.query(MesToolSnapshot).filter(MesToolSnapshot.scenario_id == scenario_id).all()
    release_rows = db.query(MesLotReleasePlan).filter(MesLotReleasePlan.scenario_id == scenario_id).all()

    wip_ids = {w.lot_id for w in wip_rows}
    tool_run = {
        t.tool_id: (t.op_state or "").upper()
        for t in tool_rows
        if (t.op_state or "").upper() in ("RUN", "SETUP")
    }

    # H4: queue lot must exist in wip (fab_env inject order)
    for q in queue_rows:
        if q.lot_id not in wip_ids:
            conflicts.append(f"queue lot {q.lot_id} missing from mes_wip_snapshot")

    # H5: PROCESSING wip needs processing_remaining_min > 0
    for w in wip_rows:
        st = (w.status or "").upper()
        if st == "PROCESSING":
            rem = w.processing_remaining_min
            if rem is None or float(rem) <= 0:
                conflicts.append(f"wip {w.lot_id} PROCESSING but processing_remaining_min missing/<=0")
            tid = (w.tool_id or "").strip()
            if tid and tid not in {t.tool_id for t in tool_rows}:
                conflicts.append(f"wip {w.lot_id} PROCESSING tool_id {tid} not in mes_tool_snapshot")

    # H5b: RUN tool snapshot vs PROCESSING wip lot_id alignment
    proc_by_tool = {
        (w.tool_id or "").strip(): w.lot_id
        for w in wip_rows
        if (w.status or "").upper() == "PROCESSING" and (w.tool_id or "").strip()
    }
    for tid, op in tool_run.items():
        run_lot = proc_by_tool.get(tid)
        if run_lot is None:
            conflicts.append(f"tool {tid} op_state={op} but no PROCESSING wip on that tool_id")

    # H6: release lot_type (preferred name) overlap with T0 wip lot_id
    wip_release_overlap = []
    for r in release_rows:
        pref = (r.lot_type or "").strip()
        if pref and pref in wip_ids:
            wip_release_overlap.append(pref)
        if float(r.release_time) <= t0:
            conflicts.append(f"release {r.id} at {r.release_time} <= t0 (builder uses > T0 only)")
    if wip_release_overlap:
        conflicts.append(f"release lot_type overlaps T0 wip: {wip_release_overlap[:5]}")

    # H7: use_master + release plan double spawn risk
    if sc.use_master_lot_release and release_rows:
        conflicts.append(
            f"use_master_lot_release=true with {len(release_rows)} plan rows (double spawn risk)"
        )

    skipped = skipped_tables or []
    stale_map = {
        "wip": len(wip_rows),
        "tools": len(tool_rows),
        "queues": len(queue_rows),
        "releases": len(release_rows),
    }
    for name in skipped:
        if name in ("forward_events", "whatif"):
            continue
        if name in stale_map and stale_map[name] > 0:
            conflicts.append(
                f"partial reload skipped --{name}: {stale_map[name]} stale DB rows remain"
            )

    return conflicts


def validate_scenario(db, scenario_id: str) -> list[str]:
    errors: list[str] = []
    sc = db.query(MesScenario).filter(MesScenario.scenario_id == scenario_id).first()
    if not sc:
        return [f"scenario not found: {scenario_id}"]
    t0, t_end = sc.t0_sim_minute, sc.t0_sim_minute + sc.horizon_minutes

    for w in db.query(MesWipSnapshot).filter(MesWipSnapshot.scenario_id == scenario_id).all():
        if abs(w.snapshot_time - t0) > 0.001:
            errors.append(f"wip {w.lot_id}: snapshot_time != t0")
        ps = db.query(ProcessStep).filter(
            ProcessStep.route_id == w.route_id, ProcessStep.step_seq == w.current_step_seq
        ).first()
        if not ps:
            errors.append(f"wip {w.lot_id}: unknown step ({w.route_id}, {w.current_step_seq})")

    for r in db.query(MesLotReleasePlan).filter(MesLotReleasePlan.scenario_id == scenario_id).all():
        if r.release_time < t0 or r.release_time > t_end:
            errors.append(f"release {r.id}: release_time {r.release_time} outside [{t0},{t_end}]")

    for e in db.query(MesForwardInputEvent).filter(MesForwardInputEvent.scenario_id == scenario_id).all():
        if e.scheduled_time < t0 or e.scheduled_time > t_end:
            errors.append(f"forward event {e.id}: time outside window")

    if sc.mode == "WHATIF":
        n = db.query(MesWhatifAction).filter(MesWhatifAction.scenario_id == scenario_id).count()
        if n == 0:
            errors.append("WHATIF scenario has no mes_whatif_action rows")
        if not sc.baseline_scenario_id:
            errors.append("WHATIF scenario missing baseline_scenario_id")

    return errors


_CORE_SNAPSHOT_TABLES = ("wip", "tools", "queues", "releases")


def _load_rows_from_path(path: Path | None) -> list[dict]:
    """Load CSV or JSON list of row dicts (actions / release patch)."""
    if path is None or not path.is_file():
        return []
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("rows"), list):
            return data["rows"]
        raise ValueError(f"JSON must be a list of rows or {{'rows': [...]}}: {path}")
    return _load_csv(path)


def _release_orm_to_dict(row: MesLotReleasePlan) -> dict:
    return {
        "scenario_id": row.scenario_id,
        "product_name": row.product_name,
        "route_name": row.route_name,
        "release_time": row.release_time,
        "lots_count": row.lots_count,
        "release_interval": row.release_interval,
        "due_date_sim": row.due_date_sim,
        "wafers_per_lot": row.wafers_per_lot,
        "priority": row.priority,
        "is_super_hot": "true" if row.is_super_hot else "false",
        "lot_type": row.lot_type or "",
        "lot_name_prefix": row.lot_name_prefix or "",
        "source_lot_release_id": row.source_lot_release_id or "",
    }


def _delete_scenario_snapshot_children(db, scenario_id: str) -> None:
    for model in (
        MesWipSnapshot,
        MesToolSnapshot,
        MesToolQueueSnapshot,
        MesLotReleasePlan,
        MesCqtSnapshot,
        MesWhatifAction,
        MesForwardInputEvent,
        MesOperatingEvent,
    ):
        db.query(model).filter(model.scenario_id == scenario_id).delete(synchronize_session=False)


def persist_whatif_from_db(
    baseline_scenario_id: str,
    whatif_scenario_id: str,
    t0: float,
    horizon: float,
    description: str,
    *,
    whatif_actions_path: Path | None = None,
    plan_patch_path: Path | None = None,
    force_draft: bool = True,
) -> dict:
    """Clone baseline mes_* from DB, apply patches/actions, persist WHATIF scenario."""
    from types import SimpleNamespace

    from tools.clone_mes_scenarios_for_monte_carlo import _copy_child_rows
    from tools.make_whatif_scenario_bundle import _patch_releases

    db = SessionLocal()
    try:
        baseline = (
            db.query(MesScenario)
            .filter(MesScenario.scenario_id == baseline_scenario_id)
            .first()
        )
        if not baseline:
            raise ValueError(f"baseline scenario not found: {baseline_scenario_id}")

        mode = (baseline.mode or "").upper().replace("-", "")
        if mode != "FORWARD":
            print(
                f"⚠️  baseline {baseline_scenario_id} mode={baseline.mode!r} (expected FORWARD)",
                file=sys.stderr,
            )

        trigger_meta = json.dumps(
            {
                "builder": "make_whatif_scenario_from_db",
                "baseline": baseline_scenario_id,
            },
            ensure_ascii=False,
        )
        args = SimpleNamespace(
            scenario_id=whatif_scenario_id,
            description=description,
            t0=t0,
            horizon=horizon,
            mode="WHATIF",
            baseline=baseline_scenario_id,
            use_master_lot_release=False,
            trigger_meta=trigger_meta,
            force_draft=force_draft,
        )
        _upsert_scenario(db, args)
        _delete_scenario_snapshot_children(db, whatif_scenario_id)
        db.flush()

        counts: dict[str, int] = {}
        clone_models = (
            MesWipSnapshot,
            MesToolSnapshot,
            MesToolQueueSnapshot,
            MesLotReleasePlan,
            MesCqtSnapshot,
        )
        for model in clone_models:
            counts[model.__tablename__] = _copy_child_rows(
                db, model, baseline_scenario_id, whatif_scenario_id,
            )

        if plan_patch_path and plan_patch_path.is_file():
            base_rows = [
                _release_orm_to_dict(r)
                for r in db.query(MesLotReleasePlan)
                .filter(MesLotReleasePlan.scenario_id == whatif_scenario_id)
                .all()
            ]
            patch_rows = _load_rows_from_path(plan_patch_path)
            patched = _patch_releases(base_rows, patch_rows, whatif_scenario_id)
            db.query(MesLotReleasePlan).filter(
                MesLotReleasePlan.scenario_id == whatif_scenario_id,
            ).delete(synchronize_session=False)
            _load_releases(db, whatif_scenario_id, patched)
            counts["mes_lot_release_plan"] = len(patched)

        action_rows = _load_rows_from_path(whatif_actions_path)
        if action_rows:
            _load_whatif(db, whatif_scenario_id, action_rows)

        db.commit()

        errs = validate_scenario(db, whatif_scenario_id)
        if errs:
            raise ValueError("validation failed: " + "; ".join(errs))

        compat = _audit_fab_env_compat(db, whatif_scenario_id)
        return {
            "baseline_scenario_id": baseline_scenario_id,
            "whatif_scenario_id": whatif_scenario_id,
            "cloned": counts,
            "actions": len(action_rows),
            "compat_warnings": compat,
        }
    finally:
        db.close()


def persist_forward_bundle_to_db(
    scenario_id: str,
    t0: float,
    horizon: float,
    description: str,
    built: dict,
    *,
    source_run_id: str | None = None,
    force_draft: bool = True,
) -> None:
    """Insert FORWARD mes_scenario + mes_* snapshots from build_forward output dict."""
    from types import SimpleNamespace

    trigger_meta = json.dumps(
        {
            **built.get("confidence", {}),
            "source_run_id": source_run_id,
            "builder": "build_forward_scenario_from_db",
        },
        ensure_ascii=False,
    )
    args = SimpleNamespace(
        scenario_id=scenario_id,
        description=description,
        t0=t0,
        horizon=horizon,
        mode="FORWARD",
        baseline="",
        use_master_lot_release=False,
        trigger_meta=trigger_meta,
        force_draft=force_draft,
    )
    db = SessionLocal()
    try:
        _upsert_scenario(db, args)
        _load_tools(db, scenario_id, built.get("tool_rows") or [])
        _load_queues(db, scenario_id, built.get("queue_rows") or [])
        _load_wip(db, scenario_id, built.get("wip_rows") or [])
        _load_releases(db, scenario_id, built.get("release_rows") or [])
        db.commit()
    finally:
        db.close()


def main() -> int:
    p = argparse.ArgumentParser(description="Load MES FORWARD/WHAT-IF scenario")
    p.add_argument("--scenario-id", required=True)
    p.add_argument("--mode", default="FORWARD", choices=("FORWARD", "WHATIF", "WHAT-IF"))
    p.add_argument("--t0", type=float, required=True)
    p.add_argument("--horizon", type=float, required=True)
    p.add_argument("--baseline", default="")
    p.add_argument("--description", default="")
    p.add_argument("--trigger-meta", default="")
    p.add_argument("--use-master-lot-release", action="store_true")
    p.add_argument("--wip", type=Path)
    p.add_argument("--tools", type=Path)
    p.add_argument("--queues", type=Path)
    p.add_argument("--releases", type=Path)
    p.add_argument("--forward-events", type=Path)
    p.add_argument("--whatif", type=Path)
    p.add_argument("--validate-only", action="store_true")
    p.add_argument("--create-tables", action="store_true")
    p.add_argument(
        "--allow-partial",
        action="store_true",
        help="Allow loading a subset of snapshot CSVs (may leave stale rows; not for FORWARD).",
    )
    p.add_argument(
        "--force-draft",
        action="store_true",
        help="Reset mes_scenario.status to DRAFT even if VALIDATED/RUNNING/DONE.",
    )
    args = p.parse_args()

    if args.create_tables:
        create_tables()

    db = SessionLocal()
    try:
        skipped_tables = []
        if not args.validate_only:
            _upsert_scenario(db, args)
            counts = {}
            if args.wip:
                counts["wip"] = _load_table_rows(db, args.scenario_id, "wip", args.wip, _load_wip)
            else:
                skipped_tables.append("wip")
            if args.tools:
                counts["tools"] = _load_table_rows(db, args.scenario_id, "tools", args.tools, _load_tools)
            else:
                skipped_tables.append("tools")
            if args.queues:
                counts["queues"] = _load_table_rows(db, args.scenario_id, "queues", args.queues, _load_queues)
            else:
                skipped_tables.append("queues")
            if args.releases:
                counts["releases"] = _load_table_rows(db, args.scenario_id, "releases", args.releases, _load_releases)
            else:
                skipped_tables.append("releases")
            if args.forward_events:
                counts["forward"] = _load_table_rows(db, args.scenario_id, "forward", args.forward_events, _load_forward_events)
            else:
                skipped_tables.append("forward_events")
            if args.whatif:
                counts["whatif"] = _load_table_rows(db, args.scenario_id, "whatif", args.whatif, _load_whatif)
            else:
                skipped_tables.append("whatif")

            core_skipped = [t for t in _CORE_SNAPSHOT_TABLES if t in skipped_tables]
            if core_skipped and not args.allow_partial:
                print(
                    "Load FAILED: partial snapshot load is not allowed for FORWARD.\n"
                    f"  Missing core tables: {core_skipped}\n"
                    "  Pass --wip --tools --queues --releases together, or use --allow-partial.",
                    file=sys.stderr,
                )
                return 1

            db.commit()
            print(f"Loaded scenario {args.scenario_id}: {counts}")
        else:
            skipped_tables = []

        errs = validate_scenario(db, args.scenario_id)
        compat = _audit_fab_env_compat(db, args.scenario_id, skipped_tables=skipped_tables)
        stale_conflicts = [c for c in compat if c.startswith("partial reload skipped")]
        if stale_conflicts and not args.allow_partial:
            print("FabEnv compat FAILED (stale snapshot rows):", file=sys.stderr)
            for w in stale_conflicts[:15]:
                print(f"  - {w}", file=sys.stderr)
            return 1
        other_compat = [c for c in compat if c not in stale_conflicts]
        if other_compat:
            print("FabEnv compat WARNINGS (load passed schema validate but may conflict at run):")
            for w in other_compat[:15]:
                print(f"  ! {w}")
            if len(other_compat) > 15:
                print(f"  ... and {len(other_compat) - 15} more")
        if errs:
            print("Validation FAILED:")
            for e in errs:
                print(f"  - {e}")
            return 1
        print("Validation OK")
        if not args.validate_only:
            sc = db.query(MesScenario).filter(MesScenario.scenario_id == args.scenario_id).first()
            if sc and sc.status == "DRAFT":
                print("Note: status is DRAFT until Trigger promotes to VALIDATED.")
            elif sc:
                print(f"Note: status preserved as {sc.status!r}.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
