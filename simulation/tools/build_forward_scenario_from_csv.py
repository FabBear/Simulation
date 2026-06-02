#!/usr/bin/env python3
"""
Build MES FORWARD scenario CSVs from cold-start sim_csv_out logs + Postgres master.

See docs/PROMPT_FORWARD_T0_FROM_SIM_CSV.md
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _float(v: Any, default: float = 0.0) -> float:
    if v is None or str(v).strip() == "":
        return default
    return float(v)


def _int(v: Any, default: int = 0) -> int:
    if v is None or str(v).strip() == "":
        return default
    return int(float(v))


def _parse_detail2(raw: Optional[str]) -> dict:
    if not raw or not str(raw).strip():
        return {}
    try:
        return json.loads(str(raw).replace('""', '"'))
    except json.JSONDecodeError:
        return {}


def _iter_csv(path: Path, run_id: str) -> Iterable[dict]:
    if not path.is_file():
        return
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("run_id") or "").strip() == run_id:
                yield row


@dataclass
class ProcessStepRow:
    route_id: str
    step_seq: int
    target_tool_group: str
    proc_unit: str
    proc_time_mean: float
    cascading_interval: Optional[float]
    setup_id: Optional[str]
    setup_time_mean: Optional[float]
    ltl_dedication_step: Optional[int]
    proc_unit_batch: bool = False

    @property
    def is_batch(self) -> bool:
        return str(self.proc_unit or "").lower() == "batch"


@dataclass
class MasterContext:
    routes: Dict[str, List[ProcessStepRow]]
    tools_by_group: Dict[str, List[str]]
    toolgroups: Dict[str, Any]
    transport_mean: float
    lot_release_defaults: Dict[Tuple[str, str], dict]
    setup_times: Dict[Tuple[str, str, str], float]  # (group, from, to) -> min

    @classmethod
    def from_db(cls) -> "MasterContext":
        from database import SessionLocal
        from models import LotRelease, ProcessStep, SetupInfo, ToolGroup, TransportTime

        db = SessionLocal()
        try:
            routes: Dict[str, List[ProcessStepRow]] = defaultdict(list)
            for s in db.query(ProcessStep).order_by(ProcessStep.route_id, ProcessStep.step_seq).all():
                routes[s.route_id].append(
                    ProcessStepRow(
                        route_id=s.route_id,
                        step_seq=int(s.step_seq),
                        target_tool_group=str(s.target_tool_group or ""),
                        proc_unit=str(s.proc_unit or "Lot"),
                        proc_time_mean=float(s.proc_time_mean or 0.0),
                        cascading_interval=s.cascading_interval,
                        setup_id=s.setup_id,
                        setup_time_mean=float(s.setup_time_mean or 0.0) if s.setup_time_mean else None,
                        ltl_dedication_step=int(s.ltl_dedication_step) if s.ltl_dedication_step else None,
                    )
                )
            tools_by_group: Dict[str, List[str]] = {}
            toolgroups = {}
            for tg in db.query(ToolGroup).all():
                name = str(tg.toolgroup_name)
                n = max(1, int(tg.num_tools or 1))
                tools_by_group[name] = [f"{name}#{i}" for i in range(1, n + 1)]
                toolgroups[name] = tg
            transport_mean = 0.0
            tr = db.query(TransportTime).first()
            if tr and tr.mean_time:
                transport_mean = float(tr.mean_time)
            lot_release_defaults = {}
            for r in db.query(LotRelease).all():
                key = (str(r.product_name or ""), str(r.route_name or ""))
                lot_release_defaults[key] = {
                    "priority": int(r.priority or 0),
                    "wafers_per_lot": int(r.wafers_per_lot or 1),
                    "is_super_hot": str(r.is_super_hot_lot or "").lower() == "yes",
                }
            setup_times = {}
            for si in db.query(SetupInfo).all():
                g = str(si.setup_group or "")
                setup_times[(g, str(si.from_setup or "None"), str(si.to_setup or "None"))] = float(si.setup_time or 0.0)
            return cls(
                routes=dict(routes),
                tools_by_group=tools_by_group,
                toolgroups=toolgroups,
                transport_mean=transport_mean,
                lot_release_defaults=lot_release_defaults,
                setup_times=setup_times,
            )
        finally:
            db.close()


@dataclass
class LotTrace:
    lot_id: str
    product: str = ""
    route_id: str = ""
    due_date_sim: float = 0.0
    arrival_time: float = -1.0
    finished_steps: Set[int] = field(default_factory=set)
    last_loading: Optional[Tuple[int, str, float, float]] = None  # step, tool_id, t, load_d
    last_open_step: Optional[int] = None  # step with activity but no FINISH
    wafers_per_lot: int = 1
    priority: int = 0
    is_super_hot: bool = False

    def is_in_fab_at(self, t0: float) -> bool:
        return self.arrival_time >= 0 and self.arrival_time <= t0


def _standard_proc_time(step: ProcessStepRow, wafers: int) -> float:
    unit = str(step.proc_unit or "Lot").lower()
    w = max(1, int(wafers))
    base = float(step.proc_time_mean or 0.0)
    if unit == "wafer":
        if step.cascading_interval and step.cascading_interval > 0:
            return base + max(0, w - 1) * float(step.cascading_interval)
        return base * w
    return base


def _route_steps(master: MasterContext, route_id: str) -> List[ProcessStepRow]:
    return master.routes.get(route_id) or []


def _step_by_seq(steps: List[ProcessStepRow], step_seq: int) -> Optional[ProcessStepRow]:
    for s in steps:
        if int(s.step_seq) == int(step_seq):
            return s
    return None


def _next_step_seq(steps: List[ProcessStepRow], finished: Set[int]) -> Optional[int]:
    for s in steps:
        if int(s.step_seq) not in finished:
            return int(s.step_seq)
    return None


def _estimate_setup_min(
    master: MasterContext,
    tool_id: str,
    step: ProcessStepRow,
    current_setup: Optional[str],
) -> float:
    if step.setup_time_mean and step.setup_time_mean > 0:
        return float(step.setup_time_mean)
    if not step.setup_id or not current_setup or current_setup == step.setup_id:
        return 0.0
    grp = tool_id.split("#")[0] if "#" in tool_id else ""
    return master.setup_times.get((grp, str(current_setup), str(step.setup_id)), 0.0)


def _estimate_remaining_min(
    t0: float,
    step: ProcessStepRow,
    wafers: int,
    transport_mean: float,
    loading: Optional[Tuple[int, str, float, float]],
    setup_d: float,
) -> float:
    proc_block = _standard_proc_time(step, wafers) + transport_mean
    if not loading or int(loading[0]) != int(step.step_seq):
        return max(1.0, proc_block)
    _step, _tool, t_load, load_d = loading
    elapsed = t0 - t_load
    if elapsed < load_d:
        return max(1.0, (load_d - elapsed) + setup_d + proc_block)
    if elapsed < load_d + setup_d:
        return max(1.0, (load_d + setup_d - elapsed) + proc_block)
    return max(1.0, proc_block - (elapsed - load_d - setup_d))


def _resolve_tool_candidates(
    master: MasterContext,
    lot_id: str,
    step: ProcessStepRow,
    ltl_lock: Dict[str, Dict[int, str]],
) -> List[str]:
    group = step.target_tool_group
    tool_ids = list(master.tools_by_group.get(group) or [])
    if not tool_ids:
        return []
    anchor = step.ltl_dedication_step
    if anchor is not None:
        locked = (ltl_lock.get(lot_id) or {}).get(int(anchor))
        if locked and locked in tool_ids:
            return [locked]
    return tool_ids


def _choose_tool(
    master: MasterContext,
    lot_id: str,
    step: ProcessStepRow,
    ltl_lock: Dict[str, Dict[int, str]],
    q_len: Dict[str, float],
    run_tool: Dict[str, Optional[str]],
) -> Optional[str]:
    cands = _resolve_tool_candidates(master, lot_id, step, ltl_lock)
    if not cands:
        return None

    def sort_key(tid: str) -> Tuple:
        tg = master.toolgroups.get(tid.split("#")[0])
        setup = 0.0
        busy = 1 if run_tool.get(tid) else 0
        qlen = q_len.get(tid, 0.0)
        return (qlen, busy, setup, tid)

    cands = sorted(cands, key=sort_key)
    return cands[0]


def _load_release_ledger(path: Path, run_id: str) -> Dict[str, dict]:
    if not path.is_file():
        return {}
    out: Dict[str, dict] = {}
    for row in _iter_csv(path, run_id):
        lot_id = (row.get("lot_id") or "").strip()
        if lot_id:
            out[lot_id] = row
    return out


def _apply_ledger_to_traces(traces: Dict[str, LotTrace], ledger: Dict[str, dict]) -> None:
    for lot_id, row in ledger.items():
        tr = traces.setdefault(lot_id, LotTrace(lot_id=lot_id))
        if row.get("due_date_sim_min") not in (None, ""):
            tr.due_date_sim = _float(row.get("due_date_sim_min"))
        sim_now = _float(row.get("sim_now_min"), -1.0)
        if sim_now >= 0:
            tr.arrival_time = sim_now
        tr.product = (row.get("product_name") or tr.product or "").strip()
        tr.route_id = (row.get("route_name") or tr.route_id or "").strip()
        if row.get("priority") not in (None, ""):
            tr.priority = _int(row.get("priority"), 0)
        sh = row.get("is_super_hot")
        if sh is not None and str(sh).strip() != "":
            tr.is_super_hot = str(sh).strip().lower() in ("1", "true", "yes")
        if row.get("wafers_per_lot") not in (None, ""):
            tr.wafers_per_lot = _int(row.get("wafers_per_lot"), 1)


def _load_lot_traces(
    path: Path,
    run_id: str,
    t_end: float,
    ledger: Optional[Dict[str, dict]] = None,
) -> Dict[str, LotTrace]:
    ledger = ledger or {}
    traces: Dict[str, LotTrace] = {}
    for row in _iter_csv(path, run_id):
        et = _float(row.get("event_time"))
        if et > t_end:
            continue
        lot_id = (row.get("lot_id") or "").strip()
        if not lot_id:
            continue
        tr = traces.setdefault(lot_id, LotTrace(lot_id=lot_id))
        tr.product = (row.get("product") or tr.product or "").strip()
        tr.route_id = (row.get("route_id") or tr.route_id or "").strip()
        ev = (row.get("event_type") or "").strip().upper()
        step_raw = row.get("step_seq")
        step_seq = _int(step_raw, -1) if step_raw not in (None, "") else -1

        if ev == "ARRIVAL":
            tr.arrival_time = et
            if lot_id in ledger and ledger[lot_id].get("due_date_sim_min") not in (None, ""):
                tr.due_date_sim = _float(ledger[lot_id].get("due_date_sim_min"))
            else:
                d2 = _parse_detail2(row.get("detail_2"))
                if "due_date_sim_min" in d2:
                    tr.due_date_sim = float(d2["due_date_sim_min"])
        elif ev == "FINISH" and step_seq >= 0:
            tr.finished_steps.add(step_seq)
            if tr.last_open_step == step_seq:
                tr.last_open_step = None
        elif ev == "LOADING" and step_seq >= 0:
            load_d = _float(row.get("detail_1"), 0.0)
            tool_id = (row.get("tool_id") or "").strip()
            tr.last_loading = (step_seq, tool_id, et, load_d)
            tr.last_open_step = step_seq
        elif ev == "BATCH_START" and step_seq >= 0:
            tool_id = (row.get("tool_id") or "").strip()
            tr.last_loading = (step_seq, tool_id, et, 0.0)
            tr.last_open_step = step_seq
        elif ev == "BATCH_MEMBER_START" and step_seq >= 0:
            tr.last_open_step = step_seq
    return traces


def _load_ltl_lock(process_path: Path, run_id: str, t0: float) -> Dict[str, Dict[int, str]]:
    lock: Dict[str, Dict[int, str]] = defaultdict(dict)
    for row in _iter_csv(process_path, run_id):
        end_t = _float(row.get("end_time"))
        if end_t > t0:
            continue
        lot_id = (row.get("lot_id") or "").strip()
        step_seq = _int(row.get("step_seq"), -1)
        tool_id = (row.get("tool_id") or "").strip()
        if lot_id and step_seq >= 0 and tool_id:
            lock[lot_id][step_seq] = tool_id
    return lock


def _load_tool_state_at(
    path: Path, run_id: str, t0: float,
) -> Tuple[Dict[str, dict], Dict[str, str]]:
    """Last unit-level tool row with state_change_time <= t0; run_lot per tool at T0."""
    last: Dict[str, dict] = {}
    for row in _iter_csv(path, run_id):
        tid = (row.get("tool_id") or "").strip()
        if not tid or "#" not in tid:
            continue
        t = _float(row.get("state_change_time"))
        if t > t0:
            continue
        prev = last.get(tid)
        if prev is None or t >= _float(prev.get("state_change_time")):
            last[tid] = dict(row)
            last[tid]["_t"] = t
    run_lot: Dict[str, str] = {}
    for tid, row in last.items():
        st = (row.get("state") or "").upper()
        if st in ("RUN", "SETUP"):
            lot = (row.get("lot_id") or "").strip()
            if lot:
                run_lot[tid] = lot
    return last, run_lot


def _load_kpi_tool_at(path: Path, run_id: str, t0: float) -> Tuple[Dict[str, float], Dict[str, float]]:
    q_len: Dict[str, float] = {}
    proc_count: Dict[str, float] = {}
    for row in _iter_csv(path, run_id):
        if _float(row.get("snapshot_time")) != float(t0):
            continue
        scope = (row.get("scope") or "").strip()
        name = (row.get("kpi_name") or "").strip()
        if "#" not in scope:
            continue
        val = _float(row.get("value"))
        if name == "q_len":
            q_len[scope] = val
        elif name == "processing_count":
            proc_count[scope] = val
    return q_len, proc_count


def _lot_defaults(master: MasterContext, tr: LotTrace) -> None:
    key = (tr.product, tr.route_id)
    d = master.lot_release_defaults.get(key) or {}
    if tr.priority == 0:
        tr.priority = int(d.get("priority", 0))
    if tr.wafers_per_lot == 1:
        tr.wafers_per_lot = int(d.get("wafers_per_lot", 1))
    if not tr.is_super_hot:
        tr.is_super_hot = bool(d.get("is_super_hot", False))


def _release_rows_from_ledger(
    ledger: Dict[str, dict],
    t0: float,
    t_end: float,
    wip_lot_ids: Set[str],
    master: MasterContext,
    traces: Dict[str, LotTrace],
    scenario_id: str,
) -> List[dict]:
    rows: List[dict] = []
    for lot_id, row in ledger.items():
        et = _float(row.get("sim_now_min"))
        if et <= t0 or et > t_end:
            continue
        if lot_id in wip_lot_ids:
            continue
        tr = traces.get(lot_id) or LotTrace(lot_id=lot_id)
        tr.product = (row.get("product_name") or tr.product or "").strip()
        tr.route_id = (row.get("route_name") or tr.route_id or "").strip()
        _lot_defaults(master, tr)
        due = _float(row.get("due_date_sim_min"), et)
        is_super = str(row.get("is_super_hot", "")).strip().lower() in ("1", "true", "yes")
        rows.append({
            "scenario_id": scenario_id,
            "product_name": tr.product,
            "route_name": tr.route_id,
            "release_time": et,
            "lots_count": 1,
            "release_interval": 0,
            "due_date_sim": due,
            "wafers_per_lot": _int(row.get("wafers_per_lot"), tr.wafers_per_lot),
            "priority": _int(row.get("priority"), tr.priority),
            "is_super_hot": "true" if is_super else "false",
            "lot_type": (row.get("lot_type") or lot_id).strip(),
            "lot_name_prefix": "",
            "source_lot_release_id": "",
        })
    return rows


def _current_step_for_lot(tr: LotTrace, steps: List[ProcessStepRow], t0: float) -> Optional[int]:
    if tr.last_open_step is not None and tr.last_open_step not in tr.finished_steps:
        return tr.last_open_step
    return _next_step_seq(steps, tr.finished_steps)


def build_scenario(
    master: MasterContext,
    run_id: str,
    t0: float,
    horizon: float,
    sim_csv_dir: Path,
    scenario_id: str,
) -> dict:
    t_end = t0 + horizon
    lot_path = sim_csv_dir / "lot_events.csv"
    ledger_path = sim_csv_dir / "lot_release_ledger.csv"
    tool_path = sim_csv_dir / "tool_state.csv"
    kpi_path = sim_csv_dir / "kpi_tool.csv"
    process_path = sim_csv_dir / "simulation_process.csv"

    ledger = _load_release_ledger(ledger_path, run_id)
    traces = _load_lot_traces(lot_path, run_id, t_end, ledger)
    _apply_ledger_to_traces(traces, ledger)
    ltl_lock = _load_ltl_lock(process_path, run_id, t0)
    tool_last, run_lot = _load_tool_state_at(tool_path, run_id, t0)
    q_len, _proc_count = _load_kpi_tool_at(kpi_path, run_id, t0)

    wip_lot_ids: Set[str] = set()
    for lid, tr in traces.items():
        if not tr.is_in_fab_at(t0):
            continue
        steps = _route_steps(master, tr.route_id)
        if not steps:
            continue
        cs = _current_step_for_lot(tr, steps, t0)
        if cs is None:
            continue
        wip_lot_ids.add(lid)

    processing: Dict[str, Tuple[str, str, int]] = {}  # lot_id -> (tool_id, route, step)
    for tid, lot in run_lot.items():
        tr = traces.get(lot)
        if not tr or lot not in wip_lot_ids:
            continue
        steps = _route_steps(master, tr.route_id)
        cs = _current_step_for_lot(tr, steps, t0) or _int(
            (tr.last_loading or (0, "", 0, 0))[0], 1
        )
        processing[lot] = (tid, tr.route_id, cs)

    queue_assign: Dict[str, List[str]] = defaultdict(list)
    for lid in wip_lot_ids:
        if lid in processing:
            continue
        tr = traces[lid]
        _lot_defaults(master, tr)
        steps = _route_steps(master, tr.route_id)
        cs = _current_step_for_lot(tr, steps, t0)
        if cs is None:
            continue
        step = _step_by_seq(steps, cs)
        if not step:
            continue
        tid = _choose_tool(master, lid, step, ltl_lock, q_len, run_lot)
        if tid:
            queue_assign[tid].append(lid)

    queue_rows: List[dict] = []
    confidence_notes: List[str] = []
    for tid, lots in queue_assign.items():
        n_kpi = int(q_len.get(tid, 0))
        lots_sorted = sorted(
            lots,
            key=lambda l: (traces[l].due_date_sim, traces[l].arrival_time, l),
        )
        if n_kpi > 0 and len(lots_sorted) > n_kpi:
            confidence_notes.append(
                f"queue {tid}: {len(lots_sorted)} candidates vs kpi q_len={n_kpi}; trimmed"
            )
            lots_sorted = lots_sorted[:n_kpi]
        elif n_kpi == 0 and lots_sorted:
            confidence_notes.append(
                f"queue {tid}: kpi q_len=0 but {len(lots_sorted)} queue candidates kept (no KPI row or empty queue)"
            )
        for pos, lid in enumerate(lots_sorted, start=1):
            tr = traces[lid]
            cs = _current_step_for_lot(tr, _route_steps(master, tr.route_id), t0) or 0
            queue_rows.append({
                "scenario_id": scenario_id,
                "tool_id": tid,
                "position": pos,
                "lot_id": lid,
                "route_id": tr.route_id,
                "step_seq": cs,
                "due_date_sim": tr.due_date_sim,
                "priority": tr.priority,
            })

    wip_rows: List[dict] = []
    for lid in sorted(wip_lot_ids):
        tr = traces[lid]
        _lot_defaults(master, tr)
        steps = _route_steps(master, tr.route_id)
        cs = _current_step_for_lot(tr, steps, t0)
        if cs is None:
            continue
        step = _step_by_seq(steps, cs)
        if not step:
            continue
        if lid in processing:
            tid, _, cs = processing[lid]
            st = "PROCESSING"
            setup_d = _estimate_setup_min(
                master, tid, step, (tool_last.get(tid) or {}).get("setup_name"),
            )
            rem = _estimate_remaining_min(
                t0, step, tr.wafers_per_lot, master.transport_mean,
                tr.last_loading, setup_d,
            )
        else:
            tid = _choose_tool(master, lid, step, ltl_lock, q_len, run_lot) or ""
            st = "QUEUING"
            rem = ""
        rem_steps = len([s for s in steps if int(s.step_seq) not in tr.finished_steps])
        wip_rows.append({
            "scenario_id": scenario_id,
            "snapshot_time": t0,
            "lot_id": lid,
            "route_id": tr.route_id,
            "current_step_seq": cs,
            "status": st,
            "tool_group": step.target_tool_group,
            "tool_id": tid,
            "queue_position": "",
            "due_date_sim": tr.due_date_sim,
            "priority": tr.priority,
            "rem_steps": rem_steps,
            "processing_remaining_min": rem if rem != "" else "",
            "wafers_per_lot": tr.wafers_per_lot,
            "product": tr.product,
            "is_super_hot": "true" if tr.is_super_hot else "false",
        })

    active_tools = (
        set(tool_last.keys())
        | set(run_lot.keys())
        | set(queue_assign.keys())
        | {t for t, _, _ in processing.values()}
    )
    tool_rows: List[dict] = []
    for tid in sorted(active_tools):
        row = tool_last.get(tid) or {}
        grp = tid.split("#")[0] if "#" in tid else tid
        tool_rows.append({
            "scenario_id": scenario_id,
            "tool_id": tid,
            "tool_group": grp,
            "op_state": (row.get("state") or "IDLE").strip().upper() or "IDLE",
            "current_setup": (row.get("setup_name") or "").strip() or "",
            "held_lot_id": "",
        })

    release_rows: List[dict] = _release_rows_from_ledger(
        ledger, t0, t_end, wip_lot_ids, master, traces, scenario_id,
    )
    ledger_release_lots = {
        lid
        for lid, row in ledger.items()
        if lid not in wip_lot_ids
        and t0 < _float(row.get("sim_now_min")) <= t_end
    }
    for row in _iter_csv(lot_path, run_id):
        if (row.get("event_type") or "").strip().upper() != "ARRIVAL":
            continue
        et = _float(row.get("event_time"))
        if et <= t0 or et > t_end:
            continue
        lot_id = (row.get("lot_id") or "").strip()
        if lot_id in wip_lot_ids or lot_id in ledger_release_lots:
            continue
        tr = traces.get(lot_id) or LotTrace(lot_id=lot_id)
        d2 = _parse_detail2(row.get("detail_2"))
        due = float(d2.get("due_date_sim_min", et))
        _lot_defaults(master, tr)
        release_rows.append({
            "scenario_id": scenario_id,
            "product_name": (row.get("product") or tr.product or "").strip(),
            "route_name": (row.get("route_id") or tr.route_id or "").strip(),
            "release_time": et,
            "lots_count": 1,
            "release_interval": 0,
            "due_date_sim": due,
            "wafers_per_lot": tr.wafers_per_lot,
            "priority": tr.priority,
            "is_super_hot": "true" if tr.is_super_hot else "false",
            "lot_type": lot_id,
            "lot_name_prefix": "",
            "source_lot_release_id": "",
        })
    if ledger:
        confidence_notes.append(
            f"release plan: {len(ledger_release_lots)} lots from lot_release_ledger.csv"
        )

    return {
        "tool_rows": tool_rows,
        "queue_rows": queue_rows,
        "wip_rows": wip_rows,
        "release_rows": release_rows,
        "confidence": {
            "run_id": run_id,
            "t0": t0,
            "horizon": horizon,
            "wip_count": len(wip_rows),
            "queue_count": len(queue_rows),
            "release_count": len(release_rows),
            "tool_count": len(tool_rows),
            "notes": confidence_notes,
        },
    }


def _write_csv(path: Path, fieldnames: List[str], rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main() -> int:
    p = argparse.ArgumentParser(description="Build FORWARD MES scenario CSVs from sim logs.")
    p.add_argument("--run-id", required=True)
    p.add_argument("--t0", type=float, required=True, help="Absolute fab sim minute (snapshot_time).")
    p.add_argument("--horizon", type=float, default=180.0)
    p.add_argument("--scenario-id", required=True)
    p.add_argument(
        "--sim-csv-dir",
        type=Path,
        default=_ROOT / "sim_csv_out",
        help="Directory with lot_events.csv, tool_state.csv, kpi_tool.csv, ...",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory (default: scenario_out/<scenario_id>).",
    )
    p.add_argument("--description", default="Built from sim_csv via build_forward_scenario_from_csv.py")
    args = p.parse_args()

    out_dir = args.out_dir or (_ROOT / "scenario_out" / args.scenario_id)
    sim_dir = args.sim_csv_dir.resolve()

    for name in ("lot_events.csv", "tool_state.csv", "kpi_tool.csv"):
        if not (sim_dir / name).is_file():
            print(f"X missing {sim_dir / name}", file=sys.stderr)
            return 1

    try:
        master = MasterContext.from_db()
    except Exception as exc:
        print(f"X Postgres master load failed: {exc}", file=sys.stderr)
        print("  Ensure docker compose db is up and init_db.py has been run.", file=sys.stderr)
        return 1

    built = build_scenario(
        master, args.run_id.strip(), float(args.t0), float(args.horizon), sim_dir, args.scenario_id,
    )

    _write_csv(
        out_dir / "mes_tool_snapshot.csv",
        ["scenario_id", "tool_id", "tool_group", "op_state", "current_setup", "held_lot_id"],
        built["tool_rows"],
    )
    _write_csv(
        out_dir / "mes_tool_queue_snapshot.csv",
        ["scenario_id", "tool_id", "position", "lot_id", "route_id", "step_seq", "due_date_sim", "priority"],
        built["queue_rows"],
    )
    _write_csv(
        out_dir / "mes_wip_snapshot.csv",
        [
            "scenario_id", "snapshot_time", "lot_id", "route_id", "current_step_seq", "status",
            "tool_group", "tool_id", "queue_position", "due_date_sim", "priority", "rem_steps",
            "processing_remaining_min", "wafers_per_lot", "product", "is_super_hot",
        ],
        built["wip_rows"],
    )
    _write_csv(
        out_dir / "mes_lot_release_plan.csv",
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
            "scenario_id": args.scenario_id,
            "mode": "FORWARD",
            "t0_sim_minute": args.t0,
            "horizon_minutes": args.horizon,
            "use_master_lot_release": False,
            "description": args.description,
            "source_run_id": args.run_id,
        }, indent=2),
        encoding="utf-8",
    )

    c = built["confidence"]
    print(f"Wrote scenario bundle -> {out_dir}")
    print(f"  tools={c['tool_count']} queues={c['queue_count']} wip={c['wip_count']} releases={c['release_count']}")
    if c["notes"]:
        for n in c["notes"][:10]:
            print(f"  note: {n}")
    print("Next:")
    print(f"  python load_mes_scenario.py --create-tables --scenario-id {args.scenario_id} \\")
    print(f"    --t0 {args.t0} --horizon {args.horizon} --description \"{args.description}\" \\")
    print(f"    --tools {out_dir / 'mes_tool_snapshot.csv'} \\")
    print(f"    --queues {out_dir / 'mes_tool_queue_snapshot.csv'} \\")
    print(f"    --wip {out_dir / 'mes_wip_snapshot.csv'} \\")
    print(f"    --releases {out_dir / 'mes_lot_release_plan.csv'}")
    print(f"  # promote to VALIDATED, then:")
    print(f"  python run_sim_forward_once.py --scenario-id {args.scenario_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
