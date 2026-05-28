import gymnasium as gym
from gymnasium import spaces
import numpy as np
import simpy
import random
import json
import csv
import os
import threading
from pathlib import Path
from collections import defaultdict, deque, Counter
from datetime import datetime
import uuid

from database import SessionLocal
from models import (
    ToolGroup, LotRelease, ProcessStep, SetupInfo, BreakdownEvent, PMEvent, TransportTime,
    SimulationLog, LotEventLog, ToolStateLog, ActiveCqtTimer, RealtimeWipSummary, KpiSnapshot,
    SimulationRun,
    MesScenario, MesScenarioRun,
    MesWipSnapshot, MesToolSnapshot, MesToolQueueSnapshot, MesCqtSnapshot,
    MesLotReleasePlan, MesWhatifAction,
)

SIM_START = datetime(2018, 1, 1, 0, 0, 0)
DEBUG_LOG_PATH = (os.environ.get("DEBUG_LOG_PATH") or "").strip()
AGENT_DEBUG_LOG_PATH = (os.environ.get("AGENT_DEBUG_LOG_PATH") or "").strip()
def _agent_log(run_id, hypothesis_id, location, message, data):
    # region agent log
    if not DEBUG_LOG_PATH:
        return
    try:
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "sessionId": "656dab",
                "runId": run_id,
                "hypothesisId": hypothesis_id,
                "location": location,
                "message": message,
                "data": data,
                "timestamp": int(datetime.now().timestamp() * 1000),
            }, ensure_ascii=True) + "\n")
    except Exception:
        pass
    # endregion


# region agent log
def _debug_log(run_id, hypothesis_id, location, message, data):
    if not AGENT_DEBUG_LOG_PATH:
        return
    try:
        with open(AGENT_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "sessionId": "b06b13",
                "id": f"log_{int(datetime.now().timestamp() * 1000)}_{uuid.uuid4().hex[:6]}",
                "timestamp": int(datetime.now().timestamp() * 1000),
                "location": location,
                "message": message,
                "data": data,
                "runId": run_id,
                "hypothesisId": hypothesis_id,
            }, ensure_ascii=True) + "\n")
    except Exception:
        pass
# endregion


# region agent log
_agent_log("pre-fix", "H6", "fab_env.py:module_import", "fab_env imported", {"file": __file__})
# endregion


class LotStat:
    def __init__(self, name, product, start_time, due_date):
        self.name = name
        self.product = product
        self.start_time = start_time
        self.end_time = None
        self.due_date = due_date
        self.setup_time_sum = 0.0
        self.q_time_violations = 0
        self.history = {}
        self.current_setup = None
        self.reworked = 0

    def get_tat(self):
        if self.end_time is not None:
            return self.end_time - self.start_time
        return 0.0


class SetupManager:
    def __init__(self, setup_list):
        self.setup_map = {}
        self.min_run_map = {}
        self.setup_group_map = {}
        for s in setup_list:
            g = str(s.setup_group) if s.setup_group else "None"
            f = str(s.from_setup) if s.from_setup else "None"
            t = str(s.to_setup) if s.to_setup else "None"
            self.setup_map[(g, f, t)] = float(s.setup_time or 0.0)
            self.min_run_map[g] = max(self.min_run_map.get(g, 0), int(s.min_run_length or 0))
            if f != "None":
                self.setup_group_map[f] = g
            if t != "None":
                self.setup_group_map[t] = g

    def infer_group(self, setup_name):
        if not setup_name:
            return "None"
        return self.setup_group_map.get(str(setup_name), "None")

    def get_setup_time(self, current_setup, next_setup):
        if current_setup == next_setup:
            return 0.0
        group = self.infer_group(next_setup)
        return self.setup_map.get((group, str(current_setup or "None"), str(next_setup or "None")), 0.0)

    def min_run_len(self, setup_name):
        return int(self.min_run_map.get(self.infer_group(setup_name), 0))


def calc_minutes(date_str):
    if isinstance(date_str, (int, float)):
        return float(max(0.0, date_str))
    s = str(date_str).strip()
    if not s or s.lower() in ["none", "nan", "nat", ""]:
        return 0.0
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%m-%d-%y %H:%M:%S",
        "%Y-%m-%d",
        "%d-%m-%Y %H:%M:%S",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(s, fmt)
            return max(0.0, (dt - SIM_START).total_seconds() / 60.0)
        except ValueError:
            continue
    return 0.0


_SIM_CSV_PROCESS_FIELDS = (
    "run_id", "lot_id", "product", "route_id", "step_seq", "step_name", "tool_group", "tool_id",
    "arrive_time", "start_time", "end_time", "queue_time", "process_time", "event_type",
)
_SIM_CSV_LOT_EVENT_FIELDS = (
    "run_id", "lot_id", "product", "route_id", "step_seq", "tool_group", "tool_id",
    "event_type", "event_time", "detail_1", "detail_2",
)
_SIM_CSV_TOOL_STATE_FIELDS = (
    "run_id", "tool_group", "tool_id", "state", "state_change_time", "setup_name", "lot_id", "reason",
    "idle_units", "run_units", "setup_units", "down_pm_units", "down_bm_units",
)
_SIM_CSV_KPI_FIELDS = (
    "run_id", "snapshot_time", "scope", "kpi_name", "value",
    "window_minutes", "numerator", "denominator", "meta",
)
_KPI_CSV_BY_LEVEL = {
    "FAB": "kpi_fab.csv",
    "PROCESS": "kpi_process.csv",
    "TOOLGROUP": "kpi_toolgroup.csv",
    "TOOL": "kpi_tool.csv",
}
# Legacy combined file (opt-in via KPI_CSV_LEGACY_COMBINED=1)
_SIM_CSV_KPI_LEGACY_FIELDS = (
    "run_id", "snapshot_time", "level", "scope", "kpi_name", "value",
    "window_minutes", "numerator", "denominator", "meta",
)

# 그룹 대표 state: 한 그룹에 여러 유닛 상태가 섞일 때 우선순위 (높을수록 먼저 채택)
_TOOL_GROUP_STATE_PRIORITY = ("DOWN_BM", "DOWN_PM", "SETUP", "RUN", "IDLE")


def _append_sim_csv(csv_dir: str, lock: threading.Lock, filename: str, fieldnames, row: dict):
    """Append one row and flush so the file stays up to date on disk (no frontend required)."""
    if not csv_dir:
        return
    path = os.path.join(csv_dir, filename)
    with lock:
        os.makedirs(csv_dir, exist_ok=True)
        is_new = not os.path.exists(path) or os.path.getsize(path) == 0
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            if is_new:
                w.writeheader()
            w.writerow({k: ("" if v is None else v) for k, v in row.items()})
            f.flush()


def draw_distribution(dist, mean, offset=0.0, rng=None):
    rng = rng or random
    d = str(dist or "constant").lower()
    mean = float(mean or 0.0)
    offset = float(offset or 0.0)
    if mean <= 0.0:
        return 0.0
    if "uniform" in d:
        return max(0.0, rng.uniform(max(0.0, mean - offset), mean + offset))
    if "normal" in d:
        return max(0.0, rng.normalvariate(mean, max(0.0, offset)))
    if "exp" in d:
        return max(0.0, rng.expovariate(1.0 / mean))
    return max(0.0, mean)


def compute_target_lead_minutes(start_date, due_date):
    return max(0.0, calc_minutes(due_date) - calc_minutes(start_date))


class _LotReleaseLike:
    """Duck-typed adapter so `MesLotReleasePlan` rows can be fed to `_source_process` unchanged.

    `_source_process` reads these attributes off of a `LotRelease` ORM object — we replicate
    only the fields it actually touches so the engine path stays identical between cold-start
    master releases and scenario release plans.
    """

    __slots__ = (
        "plan_id", "product_name", "route_name", "start_date", "due_date",
        "release_interval", "lots_per_release", "wafers_per_lot",
        "priority", "lot_type", "is_super_hot_lot",
    )

    def __init__(self, plan_id, product_name, route_name, start_delay,
                 lots_per_release, release_interval, wafers_per_lot,
                 priority, due_date_minutes, lot_type, is_super_hot_lot):
        self.plan_id = plan_id
        self.product_name = product_name
        self.route_name = route_name
        # `_source_process` calls `calc_minutes(r.start_date)` -> we pre-compute relative delay
        # and feed it back via a tagged string the parser turns into minutes.
        # Easier: monkey-patch by passing a numeric and patching `_source_process` to accept it.
        self.start_date = float(start_delay)
        # Due-date in relative-minute representation (engine compares against `sim_env.now`).
        self.due_date = float(due_date_minutes)
        self.release_interval = float(release_interval or 0.0)
        self.lots_per_release = int(lots_per_release or 1)
        self.wafers_per_lot = int(wafers_per_lot or 1)
        self.priority = int(priority or 0)
        self.lot_type = lot_type
        self.is_super_hot_lot = is_super_hot_lot


class FabEnv(gym.Env):
    metadata = {"render_modes": ["human"]}

    def __init__(self):
        super().__init__()
        self.candidate_limit = 10
        self.feature_dim = 6
        self.action_space = spaces.Discrete(self.candidate_limit)
        total_obs = 2 + (self.candidate_limit * self.feature_dim)
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(total_obs,), dtype=np.float32)

        self.sim_env = None
        self.machine_groups = {}
        self.tools = {}
        self.routes = {}
        self.batch_queues = defaultdict(list)
        self.kpi = {"lots": [], "breakdowns": [], "pm": []}
        self.active_lots_data = {}
        self.active_cqt = {}
        self.lot_ltl_lock = defaultdict(dict)
        self.transport_rule = None
        self.decision_event = None
        self.target_machine_name = None
        self.target_tool_id = None
        self.rng = random.Random(0)
        self._csv_lock = threading.Lock()
        self._csv_run_id = ""
        self.sim_end_minutes = float(os.environ.get("SIM_END_MINUTES", "200000"))
        self.pending_dispatch_index = None
        self.lot_name_seq_by_product = defaultdict(int)
        self.issued_lot_names = set()
        self._batch_group_seq = 0
        # KPI buffers (re-initialized in reset())
        self._tool_state_history = defaultdict(list)        # tool_id -> list[dict(state,start,end)]
        self._tool_process = {}                              # tool_id -> process_name
        self._process_tools = defaultdict(list)              # process_name -> [tool_id]
        self._kpi_finish_log = deque()                       # deque of (finish_time, release_time)
        self._kpi_lot_rtf = {}                               # lot_name -> {release_time, due_date, finish_time}
        self._kpi_release_count = 0                          # cumulative released lots
        self._kpi_finish_count = 0                           # cumulative finished lots
        self._kpi_batch = []                                 # buffer flushed in one DB session per snapshot pass
        self._kpi_last_emit = {}                             # cadence_min -> last sim time emitted
        # Process-level OEE inputs (sliding-window deques)
        self._kpi_proc_actual_dq = defaultdict(deque)        # proc -> deque[(t, actual_proc_time)]
        self._kpi_proc_standard_dq = defaultdict(deque)      # proc -> deque[(t, standard_proc_time)]
        self._kpi_proc_finish_dq = defaultdict(deque)        # proc -> deque[t]
        self._kpi_proc_rework_dq = defaultdict(deque)        # proc -> deque[t]
        self._kpi_proc_scrap_dq = defaultdict(deque)         # proc -> deque[t]
        # Tool-level OEE inputs (sliding-window deques) — same shape as proc deques
        self._kpi_tool_actual_dq = defaultdict(deque)        # tool_id -> deque[(t, actual_proc_time)]
        self._kpi_tool_standard_dq = defaultdict(deque)      # tool_id -> deque[(t, standard_proc_time)]
        self._kpi_tool_finish_dq = defaultdict(deque)        # tool_id -> deque[t]
        self._kpi_tool_rework_dq = defaultdict(deque)        # tool_id -> deque[t]
        self._kpi_tool_scrap_dq = defaultdict(deque)         # tool_id -> deque[t]
        self._pm_piece_count = {}                            # tool_id -> processed pieces (counter PM)
        # ---------- Scenario / FORWARD / WHAT-IF state ----------
        # `_sim_clock_offset` keeps SimPy 0..horizon while logs/KPIs report absolute (t0 + now).
        # Cold-start runs leave offset=0 so behavior is unchanged.
        self._sim_clock_offset = 0.0
        self._scenario_id = None
        self._scenario_mode = None             # None | "FORWARD" | "WHATIF"
        self._scenario_use_master_release = False
        self._mes_scenario_run_id = None
        self._mes_scenario_validation_report = {}
        self._skip_master_lot_release = False  # set true when scenario provides its own releases
        # WHAT-IF override state (consumed by dispatch helpers)
        self.dispatch_rule_override = {}       # group_name -> dispatch_rule string
        self.hold_lots = set()                 # lot_id set (skip dispatch)
        self.force_next_tool = {}              # lot_id -> {"tool_id": str, "once": bool, "tool_group": str|None}
        self.skip_release_ids = set()          # MesLotReleasePlan.id values to skip

    def _sim_csv_dir(self):
        return (os.environ.get("SIM_CSV_DIR") or "").strip()

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.rng = random.Random(0 if seed is None else int(seed))
        # region agent log
        _agent_log("pre-fix", "H1", "fab_env.py:reset:start", "reset start", {"seed": seed})
        # endregion
        # region agent log
        _debug_log("pre-fix", "H1", "fab_env.py:reset", "reset called", {"seed": seed})
        # endregion
        self.sim_env = simpy.Environment()
        self.machine_groups = {}
        self.tools = {}
        self.routes = defaultdict(list)
        self.batch_queues = defaultdict(list)
        self.kpi = {"lots": [], "breakdowns": [], "pm": []}
        self.active_lots_data = {}
        self.active_cqt = {}
        self.lot_ltl_lock = defaultdict(dict)
        self.target_tool_id = None
        self.pending_dispatch_index = None
        self._csv_run_id = uuid.uuid4().hex[:12]
        self.sim_end_minutes = float(os.environ.get("SIM_END_MINUTES", "200000"))
        self.lot_name_seq_by_product = defaultdict(int)
        self.issued_lot_names = set()
        self._batch_group_seq = 0
        self._tool_state_history = defaultdict(list)
        self._tool_process = {}
        self._process_tools = defaultdict(list)
        self._kpi_finish_log = deque()
        self._kpi_lot_rtf = {}
        self._kpi_release_count = 0
        self._kpi_finish_count = 0
        self._kpi_batch = []
        self._kpi_last_emit = {}
        self._kpi_proc_actual_dq = defaultdict(deque)
        self._kpi_proc_standard_dq = defaultdict(deque)
        self._kpi_proc_finish_dq = defaultdict(deque)
        self._kpi_proc_rework_dq = defaultdict(deque)
        self._kpi_proc_scrap_dq = defaultdict(deque)
        self._kpi_tool_actual_dq = defaultdict(deque)
        self._kpi_tool_standard_dq = defaultdict(deque)
        self._kpi_tool_finish_dq = defaultdict(deque)
        self._kpi_tool_rework_dq = defaultdict(deque)
        self._kpi_tool_scrap_dq = defaultdict(deque)
        self._pm_piece_count = {}
        # Reset per-episode scenario/what-if state.
        self._sim_clock_offset = 0.0
        self._scenario_id = None
        self._scenario_mode = None
        self._scenario_use_master_release = False
        self._mes_scenario_run_id = None
        self._mes_scenario_validation_report = {}
        self._skip_master_lot_release = False
        self.dispatch_rule_override = {}
        self.hold_lots = set()
        self.force_next_tool = {}
        self.skip_release_ids = set()

        # Resolve scenario id from options or env var.
        opts = options or {}
        scenario_id = opts.get("scenario_id") or os.environ.get("SIM_SCENARIO_ID") or None
        scenario_obj = None
        if scenario_id:
            scenario_id = str(scenario_id).strip()
            if scenario_id:
                db_pre = SessionLocal()
                try:
                    scenario_obj = (
                        db_pre.query(MesScenario)
                        .filter(MesScenario.scenario_id == scenario_id)
                        .first()
                    )
                    if not scenario_obj:
                        raise RuntimeError(f"scenario not found: {scenario_id}")
                    self._scenario_id = scenario_obj.scenario_id
                    self._scenario_mode = (scenario_obj.mode or "FORWARD").upper()
                    self._scenario_use_master_release = bool(scenario_obj.use_master_lot_release)
                    self._sim_clock_offset = float(scenario_obj.t0_sim_minute or 0.0)
                    self.sim_end_minutes = float(scenario_obj.horizon_minutes or 0.0)
                    # Master master-release spawning is skipped unless explicitly allowed.
                    self._skip_master_lot_release = not self._scenario_use_master_release
                finally:
                    db_pre.close()

        db = SessionLocal()
        try:
            master_release_spawned = self._build_simulation(db)
            if scenario_obj is not None:
                self._apply_scenario_overrides(db, scenario_obj)
            # Keep ORM rows usable after session close (PM/BD SimPy processes).
            db.expunge_all()
        finally:
            db.close()
        self._resume_simulation()
        # region agent log
        _agent_log("pre-fix", "H1", "fab_env.py:reset:end", "reset end", {
            "sim_now": float(self.sim_env.now),
            "machines": len(self.machine_groups),
            "tools": len(self.tools),
            "routes": len(self.routes),
        })
        # endregion
        return self._get_observation(), {}

    def step(self, action):
        """Dispatch: UI manual uses pending_dispatch_index; RL uses action when DISPATCH_MODE=rl; else rule."""
        rl_mode = os.getenv("DISPATCH_MODE", "rule").lower() == "rl"
        preferred_queue_index = None
        if self.pending_dispatch_index is not None:
            preferred_queue_index = int(self.pending_dispatch_index)
            self.pending_dispatch_index = None
        elif rl_mode:
            preferred_queue_index = int(action)
        if self.target_tool_id and self.target_tool_id in self.tools:
            self._dispatch_for_tool(self.target_tool_id, preferred_queue_index=preferred_queue_index)
        prev = len(self.kpi["lots"])
        self._resume_simulation()
        new_finished_count = len(self.kpi["lots"]) - prev
        reward = self._calculate_reward(new_finished_count)
        terminated = self.sim_env.now >= self.sim_end_minutes
        return self._get_observation(), reward, terminated, False, {}

    def _resume_simulation(self):
        self.decision_event = self.sim_env.event()
        timeout_event = self.sim_env.timeout(1.0)
        self.sim_env.run(until=self.decision_event | timeout_event)

    def _get_observation(self):
        tool_id = self.target_tool_id
        if not tool_id or tool_id not in self.tools:
            return np.zeros(self.observation_space.shape, dtype=np.float32)
        tool_data = self.tools[tool_id]
        queue = tool_data["queue"]
        raw_setup = str(tool_data["current_setup"] or "None")
        curr_setup_val = float(sum(ord(c) for c in raw_setup))
        obs = [curr_setup_val, float(len(queue))]
        for i in range(self.candidate_limit):
            if i < len(queue):
                lot_info = queue[i].payload
                is_setup_match = 1.0 if lot_info["req_setup"] == tool_data["current_setup"] else 0.0
                cr = self._critical_ratio(lot_info["due_date"], lot_info["rem_steps"])
                obs.extend([
                    lot_info["rem_steps"],
                    lot_info["due_date"] - self.sim_env.now,
                    is_setup_match,
                    lot_info["q_danger"],
                    lot_info["priority"],
                    1.0 if cr < 1.0 else 0.0,
                ])
            else:
                obs.extend([0.0] * self.feature_dim)
        return np.array(obs, dtype=np.float32)

    def _critical_ratio(self, due_date, rem_steps):
        remain_time = max(1.0, due_date - self.sim_env.now)
        return remain_time / max(1.0, float(rem_steps))

    def _calculate_reward(self, new_count):
        reward = -0.1
        if new_count > 0:
            reward += new_count * 500.0
            for lot in self.kpi["lots"][-new_count:]:
                if lot.q_time_violations > 0:
                    reward -= lot.q_time_violations * 50.0
        return reward

    def _log_process(self, lot_id, product, route_id, step_seq, step_name, tool_group, tool_id, arrive_time, start_time, end_time):
        qt = start_time - arrive_time
        pt = end_time - start_time
        off = float(self._sim_clock_offset)
        arrive_time = float(arrive_time) + off
        start_time = float(start_time) + off
        end_time = float(end_time) + off
        try:
            db = SessionLocal()
            db.add(SimulationLog(
                run_id=self._csv_run_id,
                lot_id=lot_id, product=product, route_id=route_id, step_seq=step_seq, step_name=step_name,
                tool_group=tool_group, tool_id=tool_id, arrive_time=arrive_time, start_time=start_time, end_time=end_time,
                queue_time=qt, process_time=pt, event_type="PROCESS",
            ))
            db.commit()
            db.close()
        except Exception:
            pass
        csv_dir = self._sim_csv_dir()
        if csv_dir:
            _append_sim_csv(
                csv_dir, self._csv_lock, "simulation_process.csv", _SIM_CSV_PROCESS_FIELDS,
                {
                    "run_id": self._csv_run_id, "lot_id": lot_id, "product": product, "route_id": route_id,
                    "step_seq": step_seq, "step_name": step_name, "tool_group": tool_group, "tool_id": tool_id,
                    "arrive_time": arrive_time, "start_time": start_time, "end_time": end_time,
                    "queue_time": qt, "process_time": pt,                     "event_type": "PROCESS",
                },
            )

    def _log_batch_process_rows(self, batch_events, route_name, step, tool_group, tool_id, start_time, end_time):
        """Write one simulation_process row per lot in a batch run (shared start/end)."""
        step_seq = int(step.step_seq)
        step_name = str(step.step_name or "")
        for evt in batch_events:
            pld = evt.payload if hasattr(evt, "payload") else {}
            member_lot = pld.get("name")
            if not member_lot:
                continue
            member_arrive = float(getattr(evt, "enqueue_time", start_time))
            self._log_process(
                member_lot,
                pld.get("product"),
                route_name,
                step_seq,
                step_name,
                tool_group,
                tool_id,
                member_arrive,
                float(start_time),
                float(end_time),
            )

    def _log_lot_event(self, lot_id, product, route_id, step_seq, tool_group, tool_id, event_type, detail_1=None, detail_2=None):
        ev_time = float(self._sim_now_abs())
        try:
            db = SessionLocal()
            db.add(LotEventLog(
                run_id=self._csv_run_id,
                lot_id=lot_id, product=product, route_id=route_id, step_seq=step_seq, tool_group=tool_group, tool_id=tool_id,
                event_type=event_type, event_time=ev_time, detail_1=detail_1, detail_2=detail_2,
            ))
            db.commit()
            db.close()
        except Exception:
            pass
        csv_dir = self._sim_csv_dir()
        if csv_dir:
            _append_sim_csv(
                csv_dir, self._csv_lock, "lot_events.csv", _SIM_CSV_LOT_EVENT_FIELDS,
                {
                    "run_id": self._csv_run_id, "lot_id": lot_id, "product": product, "route_id": route_id,
                    "step_seq": step_seq, "tool_group": tool_group, "tool_id": tool_id,
                    "event_type": event_type, "event_time": ev_time, "detail_1": detail_1, "detail_2": detail_2,
                },
            )

    def _emit_tool_state_row(self, tool_group, tool_id, state, t, setup_name, lot_id, reason, counts):
        """Write a single tool_state row to DB + CSV.

        - unit row: tool_id="<group>#k", counts=None (aggregate columns NULL)
        - aggregate row: tool_id=None (CSV: ""), counts=dict with IDLE/RUN/...
        """
        try:
            db = SessionLocal()
            db.add(ToolStateLog(
                run_id=self._csv_run_id,
                tool_group=tool_group,
                tool_id=tool_id,
                state=state,
                state_change_time=t,
                setup_name=setup_name,
                lot_id=lot_id,
                reason=reason,
                idle_units=(counts["IDLE"] if counts else None),
                run_units=(counts["RUN"] if counts else None),
                setup_units=(counts["SETUP"] if counts else None),
                down_pm_units=(counts["DOWN_PM"] if counts else None),
                down_bm_units=(counts["DOWN_BM"] if counts else None),
            ))
            db.commit()
            db.close()
        except Exception:
            pass
        csv_dir = self._sim_csv_dir()
        if csv_dir:
            _append_sim_csv(
                csv_dir, self._csv_lock, "tool_state.csv", _SIM_CSV_TOOL_STATE_FIELDS,
                {
                    "run_id": self._csv_run_id,
                    "tool_group": tool_group,
                    "tool_id": tool_id if tool_id else "",
                    "state": state,
                    "state_change_time": t,
                    "setup_name": setup_name,
                    "lot_id": lot_id,
                    "reason": reason,
                    "idle_units": (counts["IDLE"] if counts else None),
                    "run_units": (counts["RUN"] if counts else None),
                    "setup_units": (counts["SETUP"] if counts else None),
                    "down_pm_units": (counts["DOWN_PM"] if counts else None),
                    "down_bm_units": (counts["DOWN_BM"] if counts else None),
                },
            )

    def _log_tool_state(self, tool_group, tool_id, state, setup_name=None, lot_id=None,
                        reason=None, granularity="both"):
        """Write tool_state rows.

        granularity:
          - "unit"      : per-unit row only (requires valid tool_id like "Group#k")
          - "aggregate" : ToolGroup aggregate row only (tool_id NULL, counts filled)
          - "both"      : unit + aggregate (default)

        If a unit-level tool_id is not provided/recognized, falls back to "aggregate".
        """
        is_unit = bool(tool_id and "#" in str(tool_id) and tool_id in self.tools)
        if is_unit:
            self.tools[tool_id]["op_state"] = state
            self._kpi_record_unit_state(tool_id, state)
        if not is_unit:
            granularity = "aggregate"
        t = float(self._sim_now_abs())

        if granularity in ("unit", "both") and is_unit:
            self._emit_tool_state_row(
                tool_group=tool_group,
                tool_id=tool_id,
                state=state,
                t=t,
                setup_name=setup_name,
                lot_id=lot_id,
                reason=reason,
                counts=None,
            )

        if granularity in ("aggregate", "both"):
            counts = self._count_op_states_for_group(tool_group)
            rep = self._representative_group_state(counts)
            self._emit_tool_state_row(
                tool_group=tool_group,
                tool_id=None,
                state=rep,
                t=t,
                setup_name=setup_name,
                lot_id=lot_id,
                reason=reason,
                counts=counts,
            )

    def _sync_cqt_table(self, lot_id, start_step, target_step, deadline_time, started_at, is_active):
        off = float(self._sim_clock_offset)
        try:
            db = SessionLocal()
            row = db.query(ActiveCqtTimer).filter(ActiveCqtTimer.lot_id == lot_id, ActiveCqtTimer.is_active == True).first()
            if row is None:
                row = ActiveCqtTimer(
                    lot_id=lot_id, start_step=start_step, target_step=target_step,
                    deadline_time=float(deadline_time) + off,
                    started_at=float(started_at) + off,
                    is_active=is_active,
                )
                db.add(row)
            else:
                row.start_step = start_step
                row.target_step = target_step
                row.deadline_time = float(deadline_time) + off
                row.started_at = float(started_at) + off
                row.is_active = is_active
            db.commit()
            db.close()
        except Exception:
            pass

    def _parse_dispatch_flags(self, toolgroup):
        tg_name = str(getattr(toolgroup, "toolgroup_name", "") or "")
        override = self.dispatch_rule_override.get(tg_name)
        rule = str(override if override is not None else (getattr(toolgroup, "dispatch_rule", None) or "")).lower()
        return {
            "setup_avoidance": "setupavoidance" in rule or "setup avoidance" in rule,
            "superhot_enabled": "superhotlot" in rule or "super hot" in rule,
        }

    def _cqt_target_step(self, step):
        if getattr(step, "cqt_target_step", None) is not None:
            return int(step.cqt_target_step)
        if getattr(step, "cqt_start_step", None) is not None:
            return int(step.cqt_start_step)
        return None

    def _cqt_anchor_step(self, step):
        if getattr(step, "cqt_anchor_step", None) is not None:
            return int(step.cqt_anchor_step)
        if step.cqt_limit and self._cqt_target_step(step) is not None:
            return int(step.step_seq)
        return None

    def _start_cqt_timer(self, lot_name, product_name, route_name, step, m_name, tool_id):
        anchor = self._cqt_anchor_step(step)
        target = self._cqt_target_step(step)
        if not step.cqt_limit or anchor is None or target is None:
            return
        if int(step.step_seq) != anchor:
            return
        deadline = float(self.sim_env.now) + self._unit_to_minutes(step.cqt_limit, step.cqt_unit)
        self.active_cqt[lot_name] = {
            "start_step": anchor,
            "target_step": target,
            "deadline_time": deadline,
            "started_at": float(self.sim_env.now),
        }
        self._sync_cqt_table(lot_name, anchor, target, deadline, float(self.sim_env.now), True)
        self._log_lot_event(
            lot_name, product_name, route_name, anchor, m_name, tool_id,
            "CQT_START", detail_1=str(deadline),
        )

    def _end_cqt_timer(self, lot_name, product_name, route_name, step_seq, m_name, tool_id):
        if lot_name not in self.active_cqt:
            return
        timer = self.active_cqt[lot_name]
        self._log_lot_event(
            lot_name, product_name, route_name, int(step_seq), m_name, tool_id, "CQT_END",
        )
        self._sync_cqt_table(
            lot_name, timer["start_step"], timer["target_step"],
            timer["deadline_time"], timer["started_at"], False,
        )
        del self.active_cqt[lot_name]

    def _record_pm_pieces(self, tool_id, pieces):
        if tool_id and pieces > 0:
            self._pm_piece_count[tool_id] = self._pm_piece_count.get(tool_id, 0) + int(pieces)

    def _record_wip_snapshot(self):
        try:
            db = SessionLocal()
            for tool_id, tool_data in self.tools.items():
                waiting = len(tool_data["queue"])
                processing = tool_data["resource"].count
                avg_q = 0.0
                if waiting > 0:
                    avg_q = sum(max(0.0, self.sim_env.now - getattr(e, "enqueue_time", self.sim_env.now)) for e in tool_data["queue"]) / waiting
                db.add(RealtimeWipSummary(
                    snapshot_time=float(self._sim_now_abs()), tool_group=tool_data["group"], tool_id=tool_id,
                    waiting_lots=waiting, processing_lots=processing, avg_queue_time=float(avg_q)
                ))
            db.commit()
            db.close()
        except Exception:
            pass

    def _unit_to_minutes(self, value, unit):
        v = float(value or 0.0)
        u = str(unit or "min").lower()
        if "hour" in u or u == "hr" or u == "h":
            return v * 60.0
        if "day" in u or u == "d":
            return v * 1440.0
        return v

    def _count_op_states_for_group(self, group_name: str) -> dict:
        labels = ("IDLE", "RUN", "SETUP", "DOWN_PM", "DOWN_BM")
        c = {s: 0 for s in labels}
        mg = self.machine_groups.get(group_name) or {}
        for tid in mg.get("tool_ids", []):
            s = self.tools.get(tid, {}).get("op_state", "IDLE")
            if s not in c:
                s = "IDLE"
            c[s] += 1
        return c

    def _representative_group_state(self, counts: dict) -> str:
        for st in _TOOL_GROUP_STATE_PRIORITY:
            if counts.get(st, 0) > 0:
                return st
        return "IDLE"

    def _build_simulation(self, db):
        setups = db.query(SetupInfo).all()
        self.setup_mgr = SetupManager(setups)
        self.breakdowns = db.query(BreakdownEvent).all()
        self.pms = db.query(PMEvent).all()
        trans = db.query(TransportTime).all()
        self.transport_rule = trans[0] if trans else None
        tgs = db.query(ToolGroup).all()
        # region agent log
        _debug_log("pre-fix", "H2", "fab_env.py:_build_simulation", "loaded machine-side rows", {
            "toolgroups": len(tgs),
            "setups": len(setups),
            "breakdowns": len(self.breakdowns),
            "pms": len(self.pms),
            "has_transport_rule": self.transport_rule is not None
        })
        # endregion
        for tg in tgs:
            group_name = tg.toolgroup_name
            tool_count = max(1, int(tg.num_tools or 1))
            tool_ids = []
            self.machine_groups[group_name] = {"toolgroup": tg, "tool_ids": tool_ids}
            for idx in range(1, tool_count + 1):
                tool_id = f"{group_name}#{idx}"
                tool_ids.append(tool_id)
                self.tools[tool_id] = {
                    "group": group_name,
                    "tool_index": idx - 1,
                    "tool_count": tool_count,
                    "resource": simpy.PriorityResource(self.sim_env, capacity=1),
                    "queue": [],
                    "current_setup": None,
                    "last_setup": None,
                    "setup_run_count": 0,
                    "toolgroup": tg,
                    "op_state": "IDLE",
                }
                self._pm_piece_count[tool_id] = 0
            self._log_tool_state(group_name, None, "IDLE", reason="INIT")
            for bd in self.breakdowns:
                if self._matches_breakdown_scope(tg, bd):
                    for tool_id in tool_ids:
                        self.sim_env.process(self._breakdown_process(tool_id, bd))
                    break
            for pm in self.pms:
                if pm.target_tool_group and str(pm.target_tool_group).strip() and str(pm.target_tool_group) in tg.toolgroup_name:
                    for tool_id in tool_ids:
                        self.sim_env.process(self._pm_process(tool_id, pm))
            for tool_id in tool_ids:
                self.sim_env.process(self._tool_monitor(tool_id))
        steps = db.query(ProcessStep).order_by(ProcessStep.route_id, ProcessStep.step_seq).all()
        for step in steps:
            self.routes[step.route_id].append(step)
        releases = db.query(LotRelease).all()
        # region agent log
        _debug_log("pre-fix", "H2", "fab_env.py:_build_simulation", "loaded flow-side rows", {
            "process_steps": len(steps),
            "routes": len(self.routes),
            "lot_releases": len(releases)
        })
        # endregion
        # Build tool -> process(area) mapping for level-2 KPI aggregation.
        # Strategy: for each toolgroup, take the most common `area` of the steps that target it.
        # Tools whose group is never referenced fall back to the toolgroup name.
        tg_areas = defaultdict(Counter)
        for s in steps:
            if s.target_tool_group and s.area:
                tg_areas[str(s.target_tool_group)][str(s.area)] += 1
        for group_name, mg in self.machine_groups.items():
            counter = tg_areas.get(group_name)
            if counter and len(counter) > 0:
                proc_name = counter.most_common(1)[0][0]
            else:
                proc_name = group_name
            for tid in mg.get("tool_ids", []):
                self._tool_process[tid] = proc_name
                self._process_tools[proc_name].append(tid)

        master_spawned = 0
        if not self._skip_master_lot_release:
            for r in releases:
                if r.wafers_per_lot and r.wafers_per_lot > 0:
                    self.sim_env.process(self._source_process(r))
                    master_spawned += 1
        self.sim_env.process(self._snapshot_loop())
        self.sim_env.process(self._kpi_snapshot_loop())
        return master_spawned

    # =========================================================
    # Scenario / FORWARD / WHAT-IF helpers
    # =========================================================
    def _sim_now_abs(self) -> float:
        """Absolute fab-sim minute = SimPy relative time + scenario t0 offset.

        Cold start: offset==0 so returns the same as `sim_env.now`.
        Scenario  : adds `t0_sim_minute` so logs/KPIs align with MES wall clock.
        """
        try:
            return float(self.sim_env.now) + float(self._sim_clock_offset)
        except Exception:
            return float(self._sim_clock_offset)

    def _abs_to_rel(self, t_abs) -> float:
        """DB absolute sim minute -> SimPy relative (0..horizon). Clamped at 0."""
        if t_abs is None:
            return 0.0
        return max(0.0, float(t_abs) - float(self._sim_clock_offset))

    def _rel_to_abs(self, t_rel) -> float:
        return float(t_rel) + float(self._sim_clock_offset)

    def _timeout_until_abs(self, t_abs):
        """SimPy timeout from current relative time until the given absolute minute (clamped)."""
        delay = max(0.0, float(t_abs) - self._sim_now_abs())
        return self.sim_env.timeout(delay)

    def _ensure_simulation_run_row(self):
        """Insert a row in `simulation_run` for the current `_csv_run_id` if absent."""
        try:
            db = SessionLocal()
            row = db.query(SimulationRun).filter(SimulationRun.run_id == self._csv_run_id).first()
            if row is None:
                db.add(SimulationRun(
                    run_id=self._csv_run_id,
                    source_path=f"scenario:{self._scenario_id}" if self._scenario_id else None,
                    sim_end_minutes=float(self.sim_end_minutes),
                    note=f"FabEnv {'scenario' if self._scenario_id else 'cold-start'} run",
                ))
                db.commit()
            db.close()
        except Exception:
            pass

    def _apply_scenario_overrides(self, db, scenario):
        """Inject T0 snapshot, scheduled releases, and (optionally) WHAT-IF actions into SimPy."""
        self._ensure_simulation_run_row()
        # Mark scenario RUNNING + create mes_scenario_run record (session-attached row).
        try:
            sc_row = db.query(MesScenario).filter(
                MesScenario.scenario_id == scenario.scenario_id
            ).first()
            if sc_row is not None:
                sc_row.status = "RUNNING"
            run = MesScenarioRun(
                scenario_id=scenario.scenario_id,
                simulation_run_id=self._csv_run_id,
                validation_report=None,
            )
            db.add(run)
            db.commit()
            self._mes_scenario_run_id = int(run.id)
        except Exception:
            db.rollback()

        # 1) T0 snapshots — queues before WIP so pre-seeded events exist when lot processes start
        self._inject_t0_tools(db, scenario)
        self._inject_t0_queues(db, scenario)
        self._inject_t0_wip(db, scenario)
        self._inject_t0_cqt(db, scenario)

        # 2) WHAT-IF actions: apply BEFORE release spawning so immediate
        #    SKIP_RELEASE / FORCE_TOOL overrides are visible.
        if str(scenario.mode or "").upper() == "WHATIF":
            self._load_whatif_actions(db, scenario)

        # 3) Scheduled releases (FORWARD + WHATIF; master release optional)
        self._spawn_lot_release_plan(db, scenario)

    # ---- T0 snapshot injectors ------------------------------------------------

    def _inject_t0_tools(self, db, scenario):
        rows = db.query(MesToolSnapshot).filter(
            MesToolSnapshot.scenario_id == scenario.scenario_id
        ).all()
        for r in rows:
            tool = self.tools.get(r.tool_id)
            if tool is None:
                self._mes_scenario_validation_report.setdefault("missing_tools", []).append(r.tool_id)
                continue
            if r.current_setup:
                tool["current_setup"] = r.current_setup
                tool["last_setup"] = r.current_setup
            op = str(r.op_state or "IDLE").upper()
            tool["op_state"] = op
            self._kpi_record_unit_state(r.tool_id, op)
            if op in ("DOWN_PM", "DOWN_BM"):
                # Hold the resource so dispatch waits until snapshot down-state is released.
                self.sim_env.process(self._inject_down_hold(r.tool_id, op))

    def _inject_down_hold(self, tool_id, op_state):
        """Best-effort: occupy the tool with a priority=0 request to mimic DOWN at T0.

        The hold uses the master PM/BD durations the engine already knows.  When neither
        master record matches, the down state is just logged once and released so dispatch
        can resume; this keeps the simulation moving when MES snapshot disagrees with master.
        """
        tool = self.tools.get(tool_id)
        if not tool:
            return
        m_name = tool["group"]
        # Approximate down duration: average MTTR / PM duration from master tables.
        duration = 0.0
        try:
            if op_state == "DOWN_PM":
                for pm in self.pms:
                    if pm.target_tool_group and str(pm.target_tool_group) in m_name:
                        duration = max(duration, self._unit_to_minutes(pm.duration_mean, pm.duration_unit))
            elif op_state == "DOWN_BM":
                for bd in self.breakdowns:
                    if self._matches_breakdown_scope(tool["toolgroup"], bd):
                        duration = max(duration, float(bd.mttr_mean or 0.0))
        except Exception:
            duration = 0.0
        # Fall back to a short cool-down so the snapshot state at least appears in logs.
        if duration <= 0.0:
            duration = 30.0
        res = tool["resource"]
        with res.request(priority=0) as req:
            yield req
            self._log_tool_state(m_name, tool_id, op_state, reason="T0_SNAPSHOT")
            yield self.sim_env.timeout(duration)
            self._log_tool_state(m_name, tool_id, "IDLE", reason="T0_DOWN_RELEASED")

    def _inject_t0_wip(self, db, scenario):
        rows = db.query(MesWipSnapshot).filter(
            MesWipSnapshot.scenario_id == scenario.scenario_id
        ).all()
        for w in rows:
            steps = self.routes.get(w.route_id)
            if not steps:
                self._mes_scenario_validation_report.setdefault("missing_routes", []).append(w.route_id)
                continue
            # Locate the step index for current_step_seq.
            idx = next(
                (i for i, s in enumerate(steps) if int(s.step_seq) == int(w.current_step_seq)),
                None,
            )
            if idx is None:
                self._mes_scenario_validation_report.setdefault(
                    "missing_steps", []
                ).append({"route": w.route_id, "step_seq": int(w.current_step_seq)})
                continue
            lot_name = str(w.lot_id)
            self.issued_lot_names.add(lot_name)
            wafers = int(w.wafers_per_lot or 1)
            due_rel = self._abs_to_rel(w.due_date_sim) if w.due_date_sim is not None else self._abs_to_rel(0.0)
            priority = int(w.priority or 0)
            is_super = bool(w.is_super_hot)
            product = str(w.product or w.route_id)
            self.active_lots_data[lot_name] = {
                "lot_name": lot_name,
                "product": product,
                "rem_steps": int(w.rem_steps if w.rem_steps is not None else len(steps) - idx),
                "total_steps": len(steps),
                "due_date": float(due_rel),
                "start_time": float(self.sim_env.now),
                "status": str(w.status or "QUEUING"),
                "tool_id": w.tool_id,
            }
            # Track release for KPI / RTF
            self._kpi_lot_rtf[lot_name] = {
                "release_time": float(self.sim_env.now),
                "due_date": float(due_rel),
                "finish_time": None,
            }
            self._kpi_release_count += 1
            status = str(w.status or "").upper()
            if status == "PROCESSING":
                remaining = w.processing_remaining_min
                if remaining is None or remaining <= 0:
                    # Locked decision §2: treat as empty tool, FINISH immediately.
                    self._mes_scenario_validation_report.setdefault(
                        "warnings", []
                    ).append(f"WIP {lot_name} PROCESSING but processing_remaining_min missing; finishing at t0")
                    remaining = 0.0
                self.sim_env.process(self._resume_processing_wip(
                    lot_name, product, w.route_id, idx, float(remaining),
                    priority, wafers, is_super, due_rel, w.tool_id,
                ))
            else:
                # QUEUING / WAIT_TRANSPORT / WAIT_BATCH / HOLD → continue with normal lot loop from idx.
                self.sim_env.process(self._lot_process_from(
                    lot_name, product, w.route_id, float(due_rel), priority, wafers, is_super, idx,
                ))
                if status == "HOLD":
                    self.hold_lots.add(lot_name)

    def _resume_processing_wip(self, lot_name, product, route_id, idx, remaining_min,
                               priority, wafers, is_super, due_rel, tool_id):
        """Finish the currently running step (if `tool_id` is known), then continue from idx+1."""
        steps = self.routes.get(route_id) or []
        if not steps or idx >= len(steps):
            return
        step = steps[idx]
        m_name = step.target_tool_group
        if remaining_min > 0 and tool_id and tool_id in self.tools:
            tool = self.tools[tool_id]
            self._log_lot_event(
                lot_name, product, route_id, int(step.step_seq), m_name, tool_id,
                "T0_RESUME_PROCESSING", detail_1=str(remaining_min),
            )
            self._log_tool_state(m_name, tool_id, "RUN", setup_name=tool["current_setup"], lot_id=lot_name)
            with tool["resource"].request(priority=10) as req:
                yield req
                start_time = self.sim_env.now
                yield self.sim_env.timeout(float(remaining_min))
                end_time = self.sim_env.now
                self._log_process(
                    lot_name, product, route_id, int(step.step_seq), str(step.step_name or ""),
                    m_name, tool_id, float(start_time), float(start_time), float(end_time),
                )
                self._log_lot_event(lot_name, product, route_id, int(step.step_seq), m_name, tool_id, "FINISH")
                self._log_tool_state(m_name, tool_id, "IDLE", setup_name=tool["current_setup"], lot_id=lot_name)
                self.lot_ltl_lock[lot_name][int(step.step_seq)] = tool_id
        # Continue from next step
        yield self.sim_env.process(self._lot_process_from(
            lot_name, product, route_id, float(due_rel), priority, wafers, is_super, idx + 1,
        ))

    def _lot_process_from(self, lot_name, product, route_id, due_date, priority, wafers, is_super, start_idx):
        """Resume a T0 WIP lot from the given step index, skipping ARRIVAL logging."""
        yield from self._lot_process(
            lot_name, product, route_id, due_date, priority, wafers, is_super,
            start_idx=int(start_idx), suppress_init_logs=True,
        )

    def _inject_t0_queues(self, db, scenario):
        rows = (
            db.query(MesToolQueueSnapshot)
            .filter(MesToolQueueSnapshot.scenario_id == scenario.scenario_id)
            .order_by(MesToolQueueSnapshot.tool_id, MesToolQueueSnapshot.position)
            .all()
        )
        for q in rows:
            tool = self.tools.get(q.tool_id)
            if tool is None:
                continue
            ev = self.sim_env.event()
            ev.enqueue_time = float(self.sim_env.now)
            ev.payload = {
                "name": q.lot_id,
                "product": (self.active_lots_data.get(q.lot_id, {}) or {}).get("product", q.lot_id),
                "step_seq": int(q.step_seq or 0),
                "rem_steps": (self.active_lots_data.get(q.lot_id, {}) or {}).get("rem_steps", 1),
                "due_date": float(self._abs_to_rel(q.due_date_sim) if q.due_date_sim is not None else 0.0),
                "req_setup": None,
                "q_danger": 0.0,
                "priority": int(q.priority or 0),
                "is_batch": False,
                "super_hot": False,
                "tool_id": q.tool_id,
                "wafers": 1,
                "batch_leader": False,
                "batch_id": None,
                "batch_total_wafers": None,
                "batch_lot_count": None,
                "_t0_seeded": True,
            }
            tool["queue"].append(ev)

    def _inject_t0_cqt(self, db, scenario):
        rows = db.query(MesCqtSnapshot).filter(
            MesCqtSnapshot.scenario_id == scenario.scenario_id
        ).all()
        for r in rows:
            self.active_cqt[r.lot_id] = {
                "start_step": int(r.anchor_step) if r.anchor_step is not None else int(r.target_step),
                "target_step": int(r.target_step),
                "deadline_time": float(self._abs_to_rel(r.deadline_time)),
                "started_at": float(self._abs_to_rel(r.started_at)),
            }

    # ---- Release plan adapter -------------------------------------------------

    def _spawn_lot_release_plan(self, db, scenario):
        """Spawn `_source_process` for each MesLotReleasePlan row inside the horizon."""
        rows = db.query(MesLotReleasePlan).filter(
            MesLotReleasePlan.scenario_id == scenario.scenario_id
        ).all()
        spawned = 0
        for r in rows:
            if r.id in self.skip_release_ids:
                continue
            adapter = _LotReleaseLike(
                plan_id=int(r.id),
                product_name=r.product_name,
                route_name=r.route_name,
                start_delay=self._abs_to_rel(r.release_time),
                lots_per_release=int(r.lots_count or 1),
                release_interval=float(r.release_interval or 0.0),
                wafers_per_lot=int(r.wafers_per_lot or 1),
                priority=int(r.priority or 0),
                due_date_minutes=(
                    self._abs_to_rel(r.due_date_sim)
                    if r.due_date_sim is not None
                    else self._abs_to_rel(r.release_time)
                ),
                lot_type=r.lot_type,
                is_super_hot_lot="yes" if r.is_super_hot else "no",
            )
            self.sim_env.process(self._source_process(adapter))
            spawned += 1
        return spawned

    # ---- WHAT-IF actions ------------------------------------------------------

    def _load_whatif_actions(self, db, scenario):
        rows = (
            db.query(MesWhatifAction)
            .filter(MesWhatifAction.scenario_id == scenario.scenario_id)
            .order_by(MesWhatifAction.effective_time, MesWhatifAction.seq)
            .all()
        )
        now_abs = self._sim_now_abs()
        immediate, deferred = [], []
        for a in rows:
            if float(a.effective_time) <= now_abs + 1e-6:
                immediate.append(a)
            else:
                deferred.append(a)
        for a in immediate:
            self._apply_whatif_action(a)
        if deferred:
            self.sim_env.process(self._whatif_action_loop(deferred))

    def _whatif_action_loop(self, actions):
        for a in actions:
            yield self._timeout_until_abs(float(a.effective_time))
            try:
                self._apply_whatif_action(a)
            except Exception as exc:
                self._mes_scenario_validation_report.setdefault("action_errors", []).append({
                    "id": int(a.id), "kind": a.action_kind, "err": str(exc),
                })

    def _apply_whatif_action(self, a):
        kind = str(a.action_kind or "").upper()
        payload = a.payload_json or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        lot_id = a.lot_id
        if kind == "LOT_PRIORITY":
            pri = int(payload.get("priority", 0))
            if lot_id and lot_id in self.active_lots_data:
                self.active_lots_data[lot_id]["priority"] = pri
            for tool in self.tools.values():
                for ev in tool["queue"]:
                    if getattr(ev, "payload", {}).get("name") == lot_id:
                        ev.payload["priority"] = pri
        elif kind == "LOT_HOLD":
            if lot_id:
                self.hold_lots.add(lot_id)
        elif kind == "LOT_RELEASE":
            if lot_id and lot_id in self.hold_lots:
                self.hold_lots.discard(lot_id)
        elif kind == "DISPATCH_RULE_OVERRIDE":
            tg = payload.get("tool_group") or a.tool_group
            rule = payload.get("dispatch_rule")
            if tg and rule:
                self.dispatch_rule_override[str(tg)] = str(rule)
        elif kind == "FORCE_TOOL":
            tool_id = payload.get("tool_id") or a.tool_id
            once = bool(payload.get("once", False))
            tg = payload.get("tool_group") or a.tool_group
            if lot_id and tool_id:
                self.force_next_tool[lot_id] = {
                    "tool_id": str(tool_id),
                    "once": once,
                    "tool_group": (str(tg) if tg else None),
                }
        elif kind == "SKIP_RELEASE":
            rel_id = payload.get("mes_lot_release_plan_id")
            if rel_id is not None:
                self.skip_release_ids.add(int(rel_id))
        elif kind == "ADD_RELEASE":
            adapter = _LotReleaseLike(
                plan_id=None,
                product_name=str(payload.get("product_name") or ""),
                route_name=str(payload.get("route_name") or ""),
                start_delay=self._abs_to_rel(float(payload.get("release_time") or self._sim_now_abs())),
                lots_per_release=int(payload.get("lots_count") or 1),
                release_interval=float(payload.get("release_interval") or 0.0),
                wafers_per_lot=int(payload.get("wafers_per_lot") or 1),
                priority=int(payload.get("priority") or 0),
                due_date_minutes=self._abs_to_rel(
                    float(payload.get("due_date_sim") or (payload.get("release_time") or self._sim_now_abs()))
                ),
                lot_type=payload.get("lot_type"),
                is_super_hot_lot="yes" if payload.get("is_super_hot") else "no",
            )
            self.sim_env.process(self._source_process(adapter))
        else:
            self._mes_scenario_validation_report.setdefault("unknown_actions", []).append({
                "kind": kind, "id": int(a.id),
            })

    def finalize_mes_scenario_run(self):
        """Mark the scenario DONE and update mes_scenario_run.finished_at."""
        if not self._scenario_id:
            return
        try:
            db = SessionLocal()
            sc = db.query(MesScenario).filter(MesScenario.scenario_id == self._scenario_id).first()
            if sc is not None:
                sc.status = "DONE"
            if self._mes_scenario_run_id is not None:
                run = db.query(MesScenarioRun).filter(MesScenarioRun.id == self._mes_scenario_run_id).first()
                if run is not None:
                    run.finished_at = datetime.utcnow()
                    run.validation_report = self._mes_scenario_validation_report or None
            db.commit()
            db.close()
        except Exception:
            pass

    def _find_t0_preseeded_event(self, tool_id, lot_name, step_seq):
        """Return a T0 queue snapshot event if already injected (avoids duplicate queue rows)."""
        tool = self.tools.get(tool_id)
        if not tool:
            return None
        step_seq = int(step_seq)
        for evt in tool.get("queue", []):
            pld = getattr(evt, "payload", None) or {}
            if (
                pld.get("_t0_seeded")
                and pld.get("name") == lot_name
                and int(pld.get("step_seq", -1)) == step_seq
            ):
                return evt
        return None

    def _matches_breakdown_scope(self, toolgroup, bd):
        scope = str(bd.scope or "").lower()
        target = str(bd.target_name or "")
        if "area" in scope:
            return target == str(toolgroup.location or "") or target in str(toolgroup.toolgroup_name or "")
        return target in str(toolgroup.toolgroup_name or "")

    def _next_lot_name(self, product_name, preferred_name=None):
        """Return unique lot name per run; never reuse previous name."""
        product = str(product_name or "Product")
        preferred = str(preferred_name or "").strip()
        if preferred and (preferred not in self.issued_lot_names) and (preferred not in self.active_lots_data):
            self.issued_lot_names.add(preferred)
            return preferred
        while True:
            self.lot_name_seq_by_product[product] += 1
            candidate = f"Lot_{product}_{self.lot_name_seq_by_product[product]}"
            if candidate not in self.issued_lot_names and candidate not in self.active_lots_data:
                self.issued_lot_names.add(candidate)
                return candidate

    def _ensure_active_lot_entry(self, lot_name, route_name, due_date, total_steps):
        """Guard against accidental key loss during long runs."""
        if lot_name in self.active_lots_data:
            return
        self.active_lots_data[lot_name] = {
            "lot_name": lot_name,
            "product": route_name,
            "rem_steps": int(total_steps),
            "total_steps": int(total_steps),
            "due_date": float(due_date),
            "start_time": float(self.sim_env.now),
            "status": "Waiting",
            "tool_id": None,
        }

    def _event_wafers(self, evt):
        payload = evt.payload if hasattr(evt, "payload") else {}
        return max(1, int(payload.get("wafers", 1) or 1))

    def _select_batch_group(self, step, queue):
        """Build FIFO batch by wafer sum using step.batch_min/max as strict wafer limits."""
        min_wafers = max(1, int(step.batch_min or 1))
        max_wafers = max(min_wafers, int(step.batch_max or min_wafers))
        group = []
        total_wafers = 0
        for evt in queue:
            next_wafers = self._event_wafers(evt)
            candidate_group = group + [evt]
            if not self._batch_can_group(step, candidate_group):
                break
            if group and (total_wafers + next_wafers > max_wafers):
                break
            if (not group) and next_wafers > max_wafers:
                group = [evt]
                total_wafers = next_wafers
                break
            group.append(evt)
            total_wafers += next_wafers
            if total_wafers >= max_wafers:
                break
        if not group:
            return [], 0
        if total_wafers < min_wafers:
            return [], total_wafers
        return group, total_wafers

    def _source_process(self, r):
        start_delay = calc_minutes(r.start_date)
        target_lead_min = compute_target_lead_minutes(r.start_date, r.due_date)
        base_due_min = calc_minutes(r.due_date)
        release_interval = float(r.release_interval or 0.0)
        release_index = 0
        # region agent log
        _agent_log("pre-fix", "H2", "fab_env.py:_source_process", "release parsed", {
            "product": r.product_name,
            "route": r.route_name,
            "start_delay": float(start_delay),
            "target_lead_min": float(target_lead_min),
            "base_due_min": float(base_due_min),
            "release_interval": float(release_interval),
            "lots_per_release": int(r.lots_per_release or 1),
        })
        # endregion
        if start_delay > 0:
            yield self.sim_env.timeout(start_delay)
        release_count = max(1, int(r.lots_per_release or 1))
        wafers = max(1, int(r.wafers_per_lot or 1))
        is_super = str(r.is_super_hot_lot or "").lower() == "yes"

        plan_id = getattr(r, "plan_id", None)

        def _release_one_lot(lot_due_date):
            nonlocal release_index
            if plan_id is not None and plan_id in self.skip_release_ids:
                release_index += 1
                return
            preferred = r.lot_type if r.lot_type else None
            lot_name = self._next_lot_name(r.product_name, preferred_name=preferred)
            self._kpi_lot_rtf[lot_name] = {
                "release_time": float(self.sim_env.now),
                "due_date": float(lot_due_date),
                "finish_time": None,
            }
            self.sim_env.process(self._lot_process(
                lot_name, r.product_name, r.route_name, float(lot_due_date),
                int(r.priority or 0), wafers, is_super,
            ))
            self._kpi_release_count += 1
            release_index += 1

        if not release_interval or release_interval <= 0:
            for _i in range(release_count):
                _release_one_lot(float(self.sim_env.now) + float(target_lead_min))
        else:
            while True:
                for _i in range(release_count):
                    # Sliding absolute due: each release pushes due by one interval (SMT WSPW stress pattern).
                    lot_due_date = base_due_min + (release_index * release_interval)
                    _release_one_lot(lot_due_date)
                yield self.sim_env.timeout(release_interval)

    def _sample_transport(self):
        if not self.transport_rule:
            return 0.0
        return draw_distribution(self.transport_rule.dist_type, self.transport_rule.mean_time, self.transport_rule.offset_time, rng=self.rng)

    def _compute_proc_time(self, step, wafers_per_lot):
        unit_time = draw_distribution(step.proc_time_dist, step.proc_time_mean, step.proc_time_offset, rng=self.rng)
        unit = str(step.proc_unit or "Lot").lower()
        wafers = max(1, int(wafers_per_lot or 1))
        if unit == "wafer":
            if step.cascading_interval and step.cascading_interval > 0:
                return unit_time + max(0, wafers - 1) * float(step.cascading_interval)
            return unit_time * wafers
        if unit == "batch":
            return unit_time
        return unit_time

    def _compute_standard_proc_time(self, step, wafers_per_lot):
        """Same shape as `_compute_proc_time` but uses `proc_time_mean` only.

        This is the "ideal" / baseline net-process time used as the numerator of
        OEE Performance (`Σ standard / Σ actual`). Transport and load/unload are
        intentionally excluded so that performance < 1.0 reflects variability +
        transport overhead in the actual process_time.
        """
        unit_time = float(step.proc_time_mean or 0.0)
        wafers = max(1, int(wafers_per_lot or 1))
        unit = str(step.proc_unit or "Lot").lower()
        if unit == "wafer":
            if step.cascading_interval and step.cascading_interval > 0:
                return unit_time + max(0, wafers - 1) * float(step.cascading_interval)
            return unit_time * wafers
        return unit_time

    def _allowed_by_setup_avoidance(self, tool, desired_setup):
        curr = tool["current_setup"]
        if curr is None or desired_setup is None or curr == desired_setup:
            return True
        min_run = self.setup_mgr.min_run_len(curr)
        if min_run <= 0:
            return True
        return tool["setup_run_count"] >= min_run

    def _dispatch_queue_index(self, tool_id, preferred_queue_index):
        """Rule dispatch, or RL/manual: preferred index into queue[0:candidate_limit) if allowed."""
        t_data = self.tools[tool_id]
        queue = t_data["queue"]
        if not queue:
            return None
        if preferred_queue_index is not None:
            i = int(preferred_queue_index)
            if 0 <= i < len(queue):
                evt = queue[i]
                p = evt.payload if hasattr(evt, "payload") else {}
                if p.get("name") not in self.hold_lots and self._allowed_by_setup_avoidance(
                    t_data, p.get("req_setup")
                ):
                    return i
        return self._select_dispatch_candidate(tool_id, queue)

    def _dispatch_for_tool(self, tool_id, preferred_queue_index=None):
        t_data = self.tools[tool_id]
        queue = t_data["queue"]
        if not queue:
            # region agent log
            _debug_log("pre-fix", "H3", "fab_env.py:_dispatch_for_machine", "dispatch skipped due to empty queue", {
                "tool_id": tool_id
            })
            # endregion
            return
        chosen_idx = self._dispatch_queue_index(tool_id, preferred_queue_index)
        # region agent log
        _agent_log("pre-fix", "H3", "fab_env.py:_dispatch_for_machine", "dispatch choice", {
            "tool_id": tool_id,
            "queue_len": len(queue),
            "chosen_idx": int(chosen_idx),
        })
        # endregion
        evt = queue.pop(chosen_idx)
        # region agent log
        _debug_log("pre-fix", "H3", "fab_env.py:_dispatch_for_machine", "dispatch picked lot", {
            "tool_id": tool_id,
            "queue_len_before": len(queue) + 1,
            "chosen_idx": int(chosen_idx),
            "chosen_lot": evt.payload.get("name") if hasattr(evt, "payload") else None
        })
        # endregion
        if not evt.triggered:
            evt.succeed()

    def _select_dispatch_candidate(self, m_name, queue):
        t_data = self.tools[m_name]
        tg = t_data["toolgroup"]
        flags = self._parse_dispatch_flags(tg)
        # WHAT-IF: a FORCE_TOOL override targeted at this physical tool jumps the queue.
        forced_idx = None
        for idx, evt in enumerate(queue):
            p = getattr(evt, "payload", {}) or {}
            forced = self.force_next_tool.get(p.get("name"))
            if forced and forced.get("tool_id") == m_name:
                if not self._allowed_by_setup_avoidance(t_data, p.get("req_setup")):
                    continue
                forced_idx = idx
                if forced.get("once"):
                    self.force_next_tool.pop(p.get("name"), None)
                break
        if forced_idx is not None:
            return forced_idx
        ranked = []
        for idx, evt in enumerate(queue):
            p = evt.payload
            if p.get("name") in self.hold_lots:
                continue
            if not self._allowed_by_setup_avoidance(t_data, p.get("req_setup")):
                continue
            super_hot_key = 0 if p.get("super_hot", False) else 1
            setup_time = self.setup_mgr.get_setup_time(t_data["current_setup"], p.get("req_setup"))
            cr = self._critical_ratio(p.get("due_date", 0.0), p.get("rem_steps", 1))
            ranked.append((super_hot_key, -int(p.get("priority", 0)), setup_time, cr, idx))
        if not ranked:
            return 0
        # P4: superhot lots first when group rule or payload says superhot (no RUN preemption).
        if flags["superhot_enabled"] or any(queue[i].payload.get("super_hot") for i in range(len(queue))):
            super_only = [item for item in ranked if item[0] == 0]
            if super_only:
                ranked = super_only
        # Hybrid default: superhot -> highest priority -> least setup -> critical ratio
        ranked.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
        # ranking override by toolgroup columns
        rank_map = {
            str(tg.ranking_1 or "").lower(): 0,
            str(tg.ranking_2 or "").lower(): 1,
            str(tg.ranking_3 or "").lower(): 2,
        }
        if any(rank_map.keys()):
            def override_key(item):
                super_hot_key, neg_pri, setup_time, cr, idx = item
                fields = {"highest lotpriority": neg_pri, "least setuptime": setup_time, "critical ratio": cr}
                key = [super_hot_key]
                for k in [str(tg.ranking_1 or "").lower(), str(tg.ranking_2 or "").lower(), str(tg.ranking_3 or "").lower()]:
                    if k in fields:
                        key.append(fields[k])
                key.append(idx)
                return tuple(key)
            ranked.sort(key=override_key)
        return ranked[0][-1]

    def _batch_can_group(self, step, events):
        group = self.machine_groups.get(step.target_tool_group)
        if not group:
            return False
        criterion = str(group["toolgroup"].batch_criterion or "").lower()
        if "same product" in criterion and events:
            p = events[0].payload.get("product")
            if any(e.payload.get("product") != p for e in events):
                return False
        if "same step" in criterion and events:
            s = events[0].payload.get("step_seq")
            if any(e.payload.get("step_seq") != s for e in events):
                return False
        return True

    def _resolve_tool_candidates(self, lot_name, step, group_name):
        group = self.machine_groups.get(group_name)
        if not group:
            return []
        tool_ids = list(group["tool_ids"])
        anchor_step = int(step.ltl_dedication_step) if step.ltl_dedication_step is not None else None
        if anchor_step is None:
            return tool_ids
        locked_tool = self.lot_ltl_lock.get(lot_name, {}).get(anchor_step)
        if locked_tool and locked_tool in tool_ids:
            return [locked_tool]
        return tool_ids

    def _queue_other_product_count(self, tool_id, product_name):
        """How many queued lots on this tool want a different product (for product-aware tool pick)."""
        t_data = self.tools.get(tool_id)
        if not t_data:
            return 999
        pn = str(product_name or "")
        n = 0
        for e in t_data.get("queue", []):
            pld = getattr(e, "payload", None) or {}
            p = pld.get("product")
            if p is not None and str(p) != pn:
                n += 1
        return n

    def _batch_queues_other_product_count(self, tool_id, product_name):
        """Lots still in batch-wait queues for this physical tool_id but different product.

        Dispatch queue alone misses batching: lots sit in batch_queues[(route, step, tool_id)] before
        the leader is appended to tools[tool_id]['queue'].
        """
        pn = str(product_name or "")
        n = 0
        for key, q in self.batch_queues.items():
            if not key or len(key) < 3 or key[2] != tool_id:
                continue
            for evt in q or []:
                pld = getattr(evt, "payload", None) or {}
                p = pld.get("product")
                if p is not None and str(p) != pn:
                    n += 1
        return n

    def _tool_wakeup_sort_tuple(self, tool_id, step, product_name):
        t_data = self.tools[tool_id]
        tg = t_data["toolgroup"]
        wakeup = str(getattr(tg, "tool_wakeup_ranking", None) or "").lower()
        keys = []
        if "least setuptime" in wakeup or "least setup" in wakeup:
            keys.append(self.setup_mgr.get_setup_time(t_data["current_setup"], step.setup_id))
        if "shortest queue" in wakeup or "least queue" in wakeup:
            keys.append(len(t_data["queue"]))
        if "idle first" in wakeup:
            keys.append(0 if t_data["resource"].count == 0 else 1)
        other_prod = (
            self._queue_other_product_count(tool_id, product_name)
            + self._batch_queues_other_product_count(tool_id, product_name)
        )
        queue_len = len(t_data["queue"])
        busy = t_data["resource"].count
        setup_time = self.setup_mgr.get_setup_time(t_data["current_setup"], step.setup_id)
        return tuple(keys + [other_prod, busy, queue_len, setup_time, tool_id])

    def _choose_tool_for_lot(self, lot_name, step, group_name, product_name):
        candidate_ids = self._resolve_tool_candidates(lot_name, step, group_name)
        if not candidate_ids:
            return None
        # WHAT-IF FORCE_TOOL override: pin the lot to a specific tool unit if in scope.
        forced = self.force_next_tool.get(lot_name)
        if forced:
            t_id = forced.get("tool_id")
            t_grp = forced.get("tool_group")
            if t_id and t_id in candidate_ids and (not t_grp or str(t_grp) == str(group_name)):
                if forced.get("once"):
                    self.force_next_tool.pop(lot_name, None)
                return t_id
        ranked = []
        for tool_id in candidate_ids:
            t_data = self.tools[tool_id]
            if not self._allowed_by_setup_avoidance(t_data, step.setup_id):
                continue
            ranked.append(self._tool_wakeup_sort_tuple(tool_id, step, product_name))
        if not ranked:
            return candidate_ids[0]
        ranked.sort()
        return ranked[0][-1]

    def _lot_process(self, lot_name, product_name, route_name, due_date, priority,
                     wafers_per_lot, is_super_hot, start_idx=0, suppress_init_logs=False):
        steps = self.routes.get(route_name)
        if not steps:
            # region agent log
            _agent_log("pre-fix", "H2", "fab_env.py:_lot_process:no_route", "route not found", {
                "lot_name": lot_name,
                "route_name": route_name,
            })
            # endregion
            return
        # region agent log
        _debug_log("pre-fix", "H4", "fab_env.py:_lot_process", "lot entered process", {
            "lot_name": lot_name,
            "route_name": route_name,
            "step_count": len(steps),
            "due_date": float(due_date),
            "priority": int(priority)
        })
        # endregion
        stat = LotStat(lot_name, route_name, self.sim_env.now, due_date)
        self._ensure_active_lot_entry(lot_name, route_name, due_date, len(steps))
        sim_now = float(self.sim_env.now)
        due_f = float(due_date)
        remaining_to_due = max(0.0, due_f - sim_now)
        off = float(self._sim_clock_offset)
        if not suppress_init_logs:
            self._log_lot_event(
                lot_name, product_name, route_name, None, None, None, "ARRIVAL",
                detail_1=str(sim_now + off),
                detail_2=json.dumps(
                    {
                        "sim_now_min": sim_now + off,
                        "due_date_sim_min": due_f + off,
                        "remaining_to_due_min": remaining_to_due,
                    },
                    ensure_ascii=True,
                ),
            )
        i = int(start_idx)
        while i < len(steps):
            step = steps[i]
            m_name = step.target_tool_group
            if m_name not in self.machine_groups:
                # region agent log
                _agent_log("pre-fix", "H2", "fab_env.py:_lot_process:missing_machine", "target machine missing", {
                    "lot_name": lot_name,
                    "step_seq": int(step.step_seq),
                    "target_tool_group": m_name,
                })
                # endregion
                i += 1
                continue
            self._ensure_active_lot_entry(lot_name, route_name, due_date, len(steps))
            self.active_lots_data[lot_name]["status"] = "Queuing"
            self.active_lots_data[lot_name]["rem_steps"] = len(steps) - i
            arrive_time = self.sim_env.now
            self._check_cqt_timers(lot_name, stat)
            selected_tool_id = self._choose_tool_for_lot(lot_name, step, m_name, product_name)
            if selected_tool_id is None:
                yield self.sim_env.timeout(1.0)
                continue
            self.active_lots_data[lot_name]["tool_id"] = selected_tool_id
            if lot_name in self.active_cqt and int(step.step_seq) == int(self.active_cqt[lot_name]["target_step"]):
                self._end_cqt_timer(
                    lot_name, product_name, route_name, int(step.step_seq), m_name, selected_tool_id,
                )

            is_batch = str(step.proc_unit or "").lower() == "batch"
            permission_event = self._find_t0_preseeded_event(
                selected_tool_id, lot_name, int(step.step_seq),
            )
            reused_t0_queue = permission_event is not None
            if permission_event is None:
                permission_event = self.sim_env.event()
                permission_event.enqueue_time = self.sim_env.now
                permission_event.payload = {
                    "name": lot_name,
                    "product": product_name,
                    "step_seq": int(step.step_seq),
                    "rem_steps": len(steps) - i,
                    "due_date": due_date,
                    "req_setup": step.setup_id,
                    "q_danger": max(0.0, self.sim_env.now - (self.active_cqt.get(lot_name, {}).get("deadline_time", self.sim_env.now + 1e9))),
                    "priority": priority,
                    "is_batch": is_batch,
                    "super_hot": is_super_hot,
                    "tool_id": selected_tool_id,
                    "wafers": int(wafers_per_lot),
                    "batch_leader": False,
                    "batch_id": None,
                    "batch_total_wafers": None,
                    "batch_lot_count": None,
                }
            else:
                # Refresh payload for dispatch while keeping the pre-seeded queue slot.
                permission_event.payload.update({
                    "product": product_name,
                    "rem_steps": len(steps) - i,
                    "due_date": due_date,
                    "req_setup": step.setup_id,
                    "q_danger": max(0.0, self.sim_env.now - (self.active_cqt.get(lot_name, {}).get("deadline_time", self.sim_env.now + 1e9))),
                    "priority": priority,
                    "is_batch": is_batch,
                    "super_hot": is_super_hot,
                    "tool_id": selected_tool_id,
                    "wafers": int(wafers_per_lot),
                })
            run_now = False
            if is_batch:
                batch_id = (step.route_id, step.step_seq, selected_tool_id)
                self.batch_queues[batch_id].append(permission_event)
                while True:
                    queue = self.batch_queues[batch_id]
                    if queue and queue[0] is permission_event:
                        # Strict policy: never start below step.batch_min wafers.
                        group, total_wafers = self._select_batch_group(step, queue)
                        if group and permission_event in group:
                            take_n = len(group)
                            self.batch_queues[batch_id] = queue[take_n:]
                            leader = group[0]
                            followers = group[1:]
                            self._batch_group_seq += 1
                            run_batch_id = (
                                f"{step.route_id}:{int(step.step_seq)}:{selected_tool_id}:"
                                f"t{float(self.sim_env.now):.4f}:b{int(self._batch_group_seq)}"
                            )
                            batch_done_event = self.sim_env.event()
                            for idx_evt, evt in enumerate(group):
                                evt.payload["batch_leader"] = (idx_evt == 0)
                                evt.payload["batch_id"] = run_batch_id
                                evt.payload["batch_total_wafers"] = int(total_wafers)
                                evt.payload["batch_lot_count"] = int(len(group))
                                evt.payload["batch_done_event"] = batch_done_event
                                evt.payload["batch_group_events"] = group
                            for f in followers:
                                if not f.triggered:
                                    f.succeed()
                            self.tools[selected_tool_id]["queue"].append(leader)
                            self._check_trigger(selected_tool_id)
                            yield leader
                            run_now = True
                            break
                    if permission_event.triggered:
                        run_now = bool(permission_event.payload.get("batch_leader", False))
                        break
                    yield self.sim_env.timeout(1.0)
            else:
                if not reused_t0_queue:
                    self.tools[selected_tool_id]["queue"].append(permission_event)
                self._check_trigger(selected_tool_id)
                yield permission_event
                run_now = True

            if is_batch and not run_now:
                self._log_lot_event(
                    lot_name,
                    product_name,
                    route_name,
                    int(step.step_seq),
                    m_name,
                    selected_tool_id,
                    "BATCH_MEMBER_START",
                    detail_1=str(permission_event.payload.get("batch_id")),
                    detail_2=json.dumps({
                        "batch_total_wafers": int(permission_event.payload.get("batch_total_wafers") or 0),
                        "batch_lot_count": int(permission_event.payload.get("batch_lot_count") or 0),
                    }, ensure_ascii=True),
                )
                done_evt = permission_event.payload.get("batch_done_event")
                if done_evt is not None and not done_evt.triggered:
                    yield done_evt
                self._log_lot_event(
                    lot_name,
                    product_name,
                    route_name,
                    int(step.step_seq),
                    m_name,
                    selected_tool_id,
                    "BATCH_MEMBER_FINISH",
                    detail_1=str(permission_event.payload.get("batch_id")),
                    detail_2=json.dumps({
                        "batch_total_wafers": int(permission_event.payload.get("batch_total_wafers") or 0),
                        "batch_lot_count": int(permission_event.payload.get("batch_lot_count") or 0),
                    }, ensure_ascii=True),
                )

            if run_now:
                tool = self.tools[selected_tool_id]
                with tool["resource"].request(priority=10) as req:
                    yield req
                    self._ensure_active_lot_entry(lot_name, route_name, due_date, len(steps))
                    if is_batch:
                        self._log_lot_event(
                            lot_name,
                            product_name,
                            route_name,
                            int(step.step_seq),
                            m_name,
                            selected_tool_id,
                            "BATCH_START",
                            detail_1=str(permission_event.payload.get("batch_id")),
                            detail_2=json.dumps({
                                "batch_total_wafers": int(permission_event.payload.get("batch_total_wafers") or 0),
                                "batch_lot_count": int(permission_event.payload.get("batch_lot_count") or 0),
                            }, ensure_ascii=True),
                        )
                    self._log_tool_state(m_name, selected_tool_id, "RUN", setup_name=tool["current_setup"], lot_id=lot_name)
                    # loading
                    load_time = float(tool["toolgroup"].loading_time or 0.0)
                    if load_time > 0:
                        self._log_lot_event(lot_name, product_name, route_name, int(step.step_seq), m_name, selected_tool_id, "LOADING", detail_1=str(load_time))
                        yield self.sim_env.timeout(load_time)
                    # setup + setupavoidance
                    setup_time = 0.0
                    desired_setup = step.setup_id
                    if desired_setup and tool["current_setup"] != desired_setup:
                        if not self._allowed_by_setup_avoidance(tool, desired_setup):
                            # minimal run length not satisfied: keep waiting and retry
                            yield self.sim_env.timeout(1.0)
                            continue
                        setup_time = self.setup_mgr.get_setup_time(tool["current_setup"], desired_setup)
                        if setup_time > 0:
                            self._log_tool_state(m_name, selected_tool_id, "SETUP", setup_name=str(desired_setup), lot_id=lot_name)
                            yield self.sim_env.timeout(setup_time)
                        tool["current_setup"] = desired_setup
                        tool["setup_run_count"] = 0
                        stat.setup_time_sum += setup_time
                    # process
                    start_time = self.sim_env.now
                    self._ensure_active_lot_entry(lot_name, route_name, due_date, len(steps))
                    self.active_lots_data[lot_name]["status"] = "Processing"
                    proc_time = self._compute_proc_time(step, wafers_per_lot)
                    proc_time += self._sample_transport()
                    yield self.sim_env.timeout(proc_time)
                    # unloading
                    unload_time = float(tool["toolgroup"].unloading_time or 0.0)
                    if unload_time > 0:
                        yield self.sim_env.timeout(unload_time)
                    end_time = self.sim_env.now
                    # region agent log
                    _debug_log("pre-fix", "H5", "fab_env.py:_lot_process", "step completed", {
                        "lot_name": lot_name,
                        "machine": m_name,
                        "tool_id": selected_tool_id,
                        "step_seq": int(step.step_seq),
                        "arrive_time": float(arrive_time),
                        "start_time": float(start_time),
                        "end_time": float(end_time)
                    })
                    # endregion
                    tool["setup_run_count"] += 1
                    batch_events = (
                        permission_event.payload.get("batch_group_events")
                        if is_batch else None
                    )
                    if is_batch and batch_events:
                        for evt in batch_events:
                            pld = evt.payload if hasattr(evt, "payload") else {}
                            member_lot = pld.get("name")
                            if member_lot:
                                self.lot_ltl_lock[member_lot][int(step.step_seq)] = selected_tool_id
                        self._log_batch_process_rows(
                            batch_events, route_name, step, m_name, selected_tool_id,
                            float(start_time), float(end_time),
                        )
                    else:
                        self.lot_ltl_lock[lot_name][int(step.step_seq)] = selected_tool_id
                        self._log_process(
                            lot_name, product_name, route_name, int(step.step_seq), str(step.step_name or ""),
                            m_name, selected_tool_id, float(arrive_time), float(start_time), float(end_time),
                        )
                    # OEE-Performance / Quality inputs (process + tool scope counters).
                    # For batch steps this fires once per leader finish (one physical run),
                    # not once per member lot, to keep performance Σ in physical units.
                    _proc_actual = float(end_time - start_time)
                    _proc_std = self._compute_standard_proc_time(step, wafers_per_lot)
                    self._kpi_record_step_finish(
                        self._kpi_resolve_process(selected_tool_id, m_name),
                        float(end_time),
                        _proc_actual,
                        _proc_std,
                    )
                    self._kpi_record_tool_step_finish(
                        selected_tool_id,
                        float(end_time),
                        _proc_actual,
                        _proc_std,
                    )
                    self._log_lot_event(lot_name, product_name, route_name, int(step.step_seq), m_name, selected_tool_id, "FINISH")
                    self._log_tool_state(m_name, selected_tool_id, "IDLE", setup_name=tool["current_setup"], lot_id=lot_name)
                    pieces = int(
                        permission_event.payload.get("batch_total_wafers") or wafers_per_lot
                    ) if is_batch else int(wafers_per_lot)
                    self._record_pm_pieces(selected_tool_id, pieces)
                    self._start_cqt_timer(
                        lot_name, product_name, route_name, step, m_name, selected_tool_id,
                    )
                    if is_batch:
                        done_evt = permission_event.payload.get("batch_done_event")
                        if done_evt is not None and not done_evt.triggered:
                            done_evt.succeed()
            stat.history[int(step.step_seq)] = self.sim_env.now

            # sampling / rework
            if step.sampling_prob and float(step.sampling_prob) < 100.0:
                if self.rng.random() * 100.0 > float(step.sampling_prob):
                    i += 1
                    continue
            if step.rework_prob and float(step.rework_prob) > 0.0 and step.rework_target_step:
                if self.rng.random() * 100.0 < float(step.rework_prob):
                    target = int(step.rework_target_step)
                    back_idx = next((idx for idx, s in enumerate(steps) if int(s.step_seq) == target), None)
                    if back_idx is not None and back_idx < i:
                        i = back_idx
                        stat.reworked += 1
                        self._kpi_record_rework(
                            self._kpi_resolve_process(selected_tool_id, m_name),
                            float(self.sim_env.now),
                        )
                        self._kpi_record_tool_rework(selected_tool_id, float(self.sim_env.now))
                        self._log_lot_event(lot_name, product_name, route_name, int(step.step_seq), m_name, selected_tool_id, "REWORK", detail_1=str(target))
                        continue
            i += 1

        if lot_name in self.active_cqt:
            stat.q_time_violations += 1
            scrap_tid = (self.active_lots_data.get(lot_name, {}) or {}).get("tool_id")
            self._kpi_record_scrap(
                self._kpi_resolve_process(scrap_tid, None),
                float(self.sim_env.now),
            )
            self._kpi_record_tool_scrap(scrap_tid, float(self.sim_env.now))
            self._log_lot_event(lot_name, product_name, route_name, None, None, None, "SCRAP", detail_1="CQT_OPEN_AT_END")
            del self.active_cqt[lot_name]
        self.active_lots_data.pop(lot_name, None)
        stat.end_time = self.sim_env.now
        self.kpi["lots"].append(stat)
        self._kpi_finish_count += 1
        self._kpi_finish_log.append((float(stat.end_time), float(stat.start_time)))
        entry = self._kpi_lot_rtf.get(lot_name)
        if entry is not None:
            entry["finish_time"] = float(stat.end_time)

    def _check_cqt_timers(self, lot_name, stat):
        timer = self.active_cqt.get(lot_name)
        if timer and self.sim_env.now > timer["deadline_time"]:
            stat.q_time_violations += 1
            scrap_tid = (self.active_lots_data.get(lot_name, {}) or {}).get("tool_id")
            self._kpi_record_scrap(
                self._kpi_resolve_process(scrap_tid, None),
                float(self.sim_env.now),
            )
            self._kpi_record_tool_scrap(scrap_tid, float(self.sim_env.now))
            self._log_lot_event(lot_name, stat.product, stat.product, None, None, None, "SCRAP", detail_1="CQT_TIMEOUT")
            self._sync_cqt_table(lot_name, timer["start_step"], timer["target_step"], timer["deadline_time"], timer["started_at"], False)
            del self.active_cqt[lot_name]

    def _pm_process(self, tool_id, pm):
        m_name = self.tools[tool_id]["group"]
        td = self.tools[tool_id]
        tool_index = int(td.get("tool_index", 0))
        tool_count = max(1, int(td.get("tool_count", 1)))
        foa_min = self._unit_to_minutes(pm.first_occurrence or pm.mtbf, pm.foa_unit or pm.mtbf_unit)
        stagger = foa_min * (tool_index / float(tool_count)) if foa_min > 0 else 0.0
        if stagger > 0:
            yield self.sim_env.timeout(stagger)
        pieces_until_pm = max(1, int(pm.mtbf or 1))
        while True:
            if "counter" in str(pm.pm_type or "").lower():
                while self._pm_piece_count.get(tool_id, 0) < pieces_until_pm:
                    yield self.sim_env.timeout(1.0)
            else:
                interval = self._unit_to_minutes(pm.mtbf, pm.mtbf_unit)
                if interval > 0:
                    yield self.sim_env.timeout(interval)
            res = self.tools[tool_id]["resource"]
            with res.request(priority=0) as req:
                yield req
                duration = draw_distribution(pm.duration_dist, self._unit_to_minutes(pm.duration_mean, pm.duration_unit), self._unit_to_minutes(pm.duration_offset, pm.duration_unit), rng=self.rng)
                self.kpi["pm"].append((tool_id, duration))
                self._log_tool_state(m_name, tool_id, "DOWN_PM", reason=str(pm.pm_name or "PM"))
                yield self.sim_env.timeout(duration)
                self._log_tool_state(m_name, tool_id, "IDLE", reason="PM_DONE")
                if "counter" in str(pm.pm_type or "").lower():
                    self._pm_piece_count[tool_id] = 0

    def _breakdown_process(self, tool_id, bd):
        m_name = self.tools[tool_id]["group"]
        first = bd.foa_mean if bd.foa_mean else bd.mttf_mean
        if first and first > 0:
            yield self.sim_env.timeout(draw_distribution(bd.foa_dist, first, 0.0, rng=self.rng))
        while True:
            res = self.tools[tool_id]["resource"]
            with res.request(priority=0) as req:
                yield req
                repair = draw_distribution(bd.ttr_dist, bd.mttr_mean, 0.0, rng=self.rng)
                self.kpi["breakdowns"].append((tool_id, repair))
                self._log_tool_state(m_name, tool_id, "DOWN_BM", reason=str(bd.event_name or "BM"))
                yield self.sim_env.timeout(repair)
                self._log_tool_state(m_name, tool_id, "IDLE", reason="BM_DONE")
            next_fail = draw_distribution(bd.ttf_dist, bd.mttf_mean, 0.0, rng=self.rng)
            yield self.sim_env.timeout(max(1.0, next_fail))

    def _tool_monitor(self, tool_id):
        while True:
            yield self.sim_env.timeout(1.0)
            queue = self.tools[tool_id]["queue"]
            res = self.tools[tool_id]["resource"]
            if queue and (res.capacity - res.count > 0):
                self.target_machine_name = self.tools[tool_id]["group"]
                self.target_tool_id = tool_id
                if self.decision_event and (not self.decision_event.triggered):
                    self.decision_event.succeed()

    def _check_trigger(self, tool_id):
        queue = self.tools[tool_id]["queue"]
        res = self.tools[tool_id]["resource"]
        if queue and (res.capacity - res.count > 0):
            self.target_machine_name = self.tools[tool_id]["group"]
            self.target_tool_id = tool_id
            if self.decision_event and (not self.decision_event.triggered):
                self.decision_event.succeed()

    def _snapshot_loop(self):
        while True:
            yield self.sim_env.timeout(1.0)
            self._record_wip_snapshot()

    # =========================================================
    # KPI snapshot pipeline (Level 1~4, long-format kpi_snapshot DB + 4 CSV files)
    # =========================================================

    def _kpi_instant_period(self):
        try:
            return max(0.1, float(os.environ.get("KPI_INSTANT_PERIOD_MIN", "60")))
        except Exception:
            return 1.0

    def _kpi_util_window(self):
        try:
            return max(1.0, float(os.environ.get("KPI_UTIL_WINDOW_MIN", "60")))
        except Exception:
            return 60.0

    def _kpi_tat_window(self):
        try:
            return max(1.0, float(os.environ.get("KPI_TAT_WINDOW_MIN", "60")))
        except Exception:
            return 60.0

    def _kpi_throughput_window(self):
        try:
            return max(1.0, float(os.environ.get("KPI_THROUGHPUT_WINDOW_MIN", "1440")))
        except Exception:
            return 1440.0

    def _kpi_loop_tick(self):
        """SimPy timeout between KPI checks = smallest active cadence."""
        return min(
            self._kpi_instant_period(),
            self._kpi_util_window(),
            self._kpi_tat_window(),
            self._kpi_throughput_window(),
        )

    def _kpi_max_window(self):
        """Largest lookback any KPI uses; tool state history retention."""
        return max(
            self._kpi_util_window(),
            self._kpi_tat_window(),
            self._kpi_throughput_window(),
            1.0,
        )

    def _kpi_cadences_due(self, t_now):
        """Return cadence values due at t_now; update last_emit once per cadence per pass."""
        due = set()
        for cadence in (
            self._kpi_instant_period(),
            self._kpi_util_window(),
            self._kpi_tat_window(),
            self._kpi_throughput_window(),
        ):
            last = self._kpi_last_emit.get(cadence, -1e18)
            if t_now - last >= cadence - 1e-6:
                due.add(cadence)
        for cadence in due:
            self._kpi_last_emit[cadence] = t_now
        return due

    def _kpi_record_unit_state(self, tool_id, state):
        """Close prior interval and open a new one for utilization windows."""
        if tool_id not in self.tools:
            return
        t = float(self.sim_env.now)
        hist = self._tool_state_history[tool_id]
        if hist:
            last = hist[-1]
            if last.get("end") is None:
                last["end"] = t
        hist.append({"state": state, "start": t, "end": None})
        # Trim history older than the largest window (keep one extra entry that may overlap left edge).
        cutoff = t - self._kpi_max_window() - 1.0
        i = 0
        while i + 1 < len(hist) and (hist[i].get("end") or t) < cutoff:
            i += 1
        if i > 0:
            del hist[:i]

    def _kpi_unit_state_time_in_window(self, tool_id, window_min, t_now):
        """Sum time spent in each state during [t_now - window, t_now] for one unit."""
        result = {"IDLE": 0.0, "RUN": 0.0, "SETUP": 0.0, "DOWN_PM": 0.0, "DOWN_BM": 0.0}
        if window_min <= 0:
            return result
        win_start = t_now - float(window_min)
        win_end = t_now
        hist = self._tool_state_history.get(tool_id, [])
        for iv in hist:
            s = iv.get("state", "IDLE")
            iv_start = float(iv.get("start", 0.0))
            iv_end = float(iv.get("end") if iv.get("end") is not None else win_end)
            seg_start = max(iv_start, win_start)
            seg_end = min(iv_end, win_end)
            dur = max(0.0, seg_end - seg_start)
            if dur <= 0.0:
                continue
            if s not in result:
                s = "IDLE"
            result[s] += dur
        return result

    def _kpi_trim_finish_log(self, t_now, max_window):
        cutoff = t_now - float(max_window)
        while self._kpi_finish_log and self._kpi_finish_log[0][0] < cutoff:
            self._kpi_finish_log.popleft()

    def _kpi_resolve_process(self, tool_id, fallback_group):
        """Map a tool unit (or its group) to the process bucket used by KPI emit."""
        proc = self._tool_process.get(tool_id) if tool_id else None
        if proc:
            return proc
        return str(fallback_group) if fallback_group else None

    def _kpi_record_step_finish(self, proc_name, t, actual, standard):
        if not proc_name:
            return
        self._kpi_proc_finish_dq[proc_name].append(t)
        self._kpi_proc_actual_dq[proc_name].append((t, float(actual)))
        self._kpi_proc_standard_dq[proc_name].append((t, float(standard)))

    def _kpi_record_rework(self, proc_name, t):
        if not proc_name:
            return
        self._kpi_proc_rework_dq[proc_name].append(t)

    def _kpi_record_scrap(self, proc_name, t):
        if proc_name:
            self._kpi_proc_scrap_dq[proc_name].append(t)

    def _kpi_record_tool_step_finish(self, tool_id, t, actual, standard):
        if not tool_id:
            return
        self._kpi_tool_finish_dq[tool_id].append(t)
        self._kpi_tool_actual_dq[tool_id].append((t, float(actual)))
        self._kpi_tool_standard_dq[tool_id].append((t, float(standard)))

    def _kpi_record_tool_rework(self, tool_id, t):
        if not tool_id:
            return
        self._kpi_tool_rework_dq[tool_id].append(t)

    def _kpi_record_tool_scrap(self, tool_id, t):
        if not tool_id:
            return
        self._kpi_tool_scrap_dq[tool_id].append(t)

    def _kpi_trim_value_dq(self, dq, cutoff):
        while dq and dq[0][0] < cutoff:
            dq.popleft()

    def _kpi_trim_time_dq(self, dq, cutoff):
        while dq and dq[0] < cutoff:
            dq.popleft()

    def _kpi_trim_process_dqs(self, t_now):
        cutoff = t_now - self._kpi_max_window()
        for d in self._kpi_proc_finish_dq.values():
            self._kpi_trim_time_dq(d, cutoff)
        for d in self._kpi_proc_rework_dq.values():
            self._kpi_trim_time_dq(d, cutoff)
        for d in self._kpi_proc_scrap_dq.values():
            self._kpi_trim_time_dq(d, cutoff)
        for d in self._kpi_proc_actual_dq.values():
            self._kpi_trim_value_dq(d, cutoff)
        for d in self._kpi_proc_standard_dq.values():
            self._kpi_trim_value_dq(d, cutoff)

    def _kpi_trim_tool_dqs(self, t_now):
        cutoff = t_now - self._kpi_max_window()
        for d in self._kpi_tool_finish_dq.values():
            self._kpi_trim_time_dq(d, cutoff)
        for d in self._kpi_tool_rework_dq.values():
            self._kpi_trim_time_dq(d, cutoff)
        for d in self._kpi_tool_scrap_dq.values():
            self._kpi_trim_time_dq(d, cutoff)
        for d in self._kpi_tool_actual_dq.values():
            self._kpi_trim_value_dq(d, cutoff)
        for d in self._kpi_tool_standard_dq.values():
            self._kpi_trim_value_dq(d, cutoff)

    @staticmethod
    def _kpi_count_in_window(dq, t_now, w):
        if w <= 0 or not dq:
            return 0
        cutoff = t_now - w
        return sum(1 for t in dq if t >= cutoff)

    @staticmethod
    def _kpi_sum_in_window(dq, t_now, w):
        if w <= 0 or not dq:
            return 0.0
        cutoff = t_now - w
        return float(sum(v for t, v in dq if t >= cutoff))

    def _log_kpi_snapshot(self, level, scope, kpi_name, value,
                          window_minutes=None, numerator=None, denominator=None, meta=None,
                          snapshot_time=None):
        """Append one KPI row to DB batch + level-specific CSV (cadence gating is in _emit_all_kpis).

        `snapshot_time`, when provided by the caller, is expected to be in relative SimPy minutes;
        we convert it to absolute (`t0 + now`) so DB/CSV consumers always see absolute fab time.
        """
        rel = float(self.sim_env.now if snapshot_time is None else snapshot_time)
        t = rel + float(self._sim_clock_offset)
        v = None if value is None else float(value)
        wm = None if window_minutes is None else int(window_minutes)
        num = None if numerator is None else float(numerator)
        den = None if denominator is None else float(denominator)
        if not hasattr(self, "_kpi_batch") or self._kpi_batch is None:
            self._kpi_batch = []
        self._kpi_batch.append({
            "run_id": self._csv_run_id,
            "snapshot_time": t, "level": level, "scope": scope, "kpi_name": kpi_name,
            "value": v, "window_minutes": wm, "numerator": num, "denominator": den, "meta": meta,
        })
        csv_dir = self._sim_csv_dir()
        if not csv_dir:
            return
        row = {
            "run_id": self._csv_run_id,
            "snapshot_time": t,
            "scope": scope,
            "kpi_name": kpi_name,
            "value": ("" if v is None else v),
            "window_minutes": ("" if wm is None else wm),
            "numerator": ("" if num is None else num),
            "denominator": ("" if den is None else den),
            "meta": ("" if meta is None else meta),
        }
        csv_name = _KPI_CSV_BY_LEVEL.get(level)
        if csv_name:
            _append_sim_csv(csv_dir, self._csv_lock, csv_name, _SIM_CSV_KPI_FIELDS, row)
        if os.environ.get("KPI_CSV_LEGACY_COMBINED", "").strip().lower() in ("1", "true", "yes"):
            legacy = dict(row)
            legacy["level"] = level
            _append_sim_csv(
                csv_dir, self._csv_lock, "kpi_snapshot.csv", _SIM_CSV_KPI_LEGACY_FIELDS, legacy,
            )

    def _flush_kpi_batch(self):
        """One DB session per snapshot pass — much cheaper than per-row session/commit."""
        rows = getattr(self, "_kpi_batch", None) or []
        if not rows:
            return
        try:
            db = SessionLocal()
            db.bulk_insert_mappings(KpiSnapshot, rows)
            db.commit()
            db.close()
        except Exception:
            pass
        self._kpi_batch = []

    def _kpi_snapshot_loop(self):
        tick = self._kpi_loop_tick()
        while True:
            yield self.sim_env.timeout(tick)
            self._emit_all_kpis()

    def _emit_all_kpis(self):
        t_now = float(self.sim_env.now)
        instant_p = self._kpi_instant_period()
        util_w = self._kpi_util_window()
        tat_w = self._kpi_tat_window()
        tput_w = self._kpi_throughput_window()
        self._kpi_trim_finish_log(t_now, self._kpi_max_window())
        self._kpi_trim_process_dqs(t_now)
        self._kpi_trim_tool_dqs(t_now)
        due = self._kpi_cadences_due(t_now)
        self._kpi_batch = []
        try:
            if instant_p in due:
                self._emit_fab_kpis_instant(t_now)
                self._emit_process_kpis_instant(t_now)
                self._emit_toolgroup_kpis_instant(t_now)
                self._emit_tool_kpis_instant(t_now)
            if util_w in due:
                self._emit_fab_kpis_util(t_now, util_w)
                self._emit_process_kpis_util(t_now, util_w)
                self._emit_toolgroup_kpis_util(t_now, util_w)
                self._emit_tool_kpis_util(t_now, util_w)
            if tat_w in due:
                self._emit_fab_kpis_tat(t_now, tat_w)
            if tput_w in due:
                self._emit_fab_kpis_throughput(t_now, tput_w)
            self._flush_kpi_batch()
        except Exception:
            self._kpi_batch = []

    def _emit_fab_kpis_instant(self, t_now):
        finished = float(self._kpi_finish_count)
        released = float(self._kpi_release_count)
        due_due = 0
        on_time = 0
        for entry in self._kpi_lot_rtf.values():
            due = float(entry["due_date"])
            if due > t_now:
                continue
            due_due += 1
            fin = entry.get("finish_time")
            if fin is not None and float(fin) <= due:
                on_time += 1
        rtf_value = (on_time / due_due) if due_due > 0 else 0.0
        self._log_kpi_snapshot(
            "FAB", "*", "rtf", rtf_value,
            window_minutes=None,
            numerator=float(on_time),
            denominator=float(due_due),
            meta=json.dumps({"on_time": on_time, "due_due": due_due}) if due_due else None,
        )
        completion_rate = (finished / released) if released > 0 else 0.0
        self._log_kpi_snapshot(
            "FAB", "*", "completion_rate", completion_rate,
            window_minutes=None, numerator=finished, denominator=released,
        )
        total_waiting = 0
        total_processing = 0
        q_time_sum = 0.0
        for tid, td in self.tools.items():
            q = td["queue"]
            waiting = len(q)
            total_waiting += waiting
            total_processing += td["resource"].count
            for evt in q:
                q_time_sum += max(0.0, t_now - getattr(evt, "enqueue_time", t_now))
        q_time_value = (q_time_sum / total_waiting) if total_waiting > 0 else 0.0
        self._log_kpi_snapshot(
            "FAB", "*", "q_time_min", q_time_value,
            window_minutes=None, numerator=q_time_sum, denominator=float(total_waiting),
        )
        self._log_kpi_snapshot(
            "FAB", "*", "wip", float(total_waiting + total_processing),
            window_minutes=None, numerator=float(total_waiting), denominator=float(total_processing),
        )

    def _emit_fab_kpis_util(self, t_now, util_w):
        run_sum = 0.0
        n_units = 0
        for tid in self.tools:
            run_sum += self._kpi_unit_state_time_in_window(tid, util_w, t_now)["RUN"]
            n_units += 1
        denom = util_w * max(1, n_units)
        util_value = (run_sum / denom) if denom > 0 else 0.0
        self._log_kpi_snapshot(
            "FAB", "*", "utilization", util_value,
            window_minutes=int(util_w), numerator=run_sum, denominator=denom,
        )

    def _emit_fab_kpis_tat(self, t_now, tat_w):
        tats = [(ev[0] - ev[1]) for ev in self._kpi_finish_log if ev[0] >= t_now - tat_w]
        tat_sum = float(sum(tats))
        tat_n = float(len(tats))
        tat_value = (tat_sum / tat_n) if tat_n > 0 else 0.0
        self._log_kpi_snapshot(
            "FAB", "*", "tat_min", tat_value,
            window_minutes=int(tat_w), numerator=tat_sum, denominator=tat_n,
        )

    def _emit_fab_kpis_throughput(self, t_now, tput_w):
        tp_count = sum(1 for ev in self._kpi_finish_log if ev[0] >= t_now - tput_w)
        self._log_kpi_snapshot(
            "FAB", "*", "throughput_24h", float(tp_count),
            window_minutes=int(tput_w), numerator=float(tp_count), denominator=None,
        )

    def _emit_process_kpis_instant(self, t_now):
        for proc_name, tool_ids in self._process_tools.items():
            if not tool_ids:
                continue
            q_sum = 0.0
            waiting = 0
            processing = 0
            for tid in tool_ids:
                td = self.tools.get(tid)
                if not td:
                    continue
                waiting += len(td["queue"])
                processing += td["resource"].count
                for evt in td["queue"]:
                    q_sum += max(0.0, t_now - getattr(evt, "enqueue_time", t_now))
            q_value = (q_sum / waiting) if waiting > 0 else 0.0
            self._log_kpi_snapshot(
                "PROCESS", proc_name, "q_time_min", q_value,
                window_minutes=None, numerator=q_sum, denominator=float(waiting),
            )
            self._log_kpi_snapshot(
                "PROCESS", proc_name, "wip", float(waiting + processing),
                window_minutes=None, numerator=float(waiting), denominator=float(processing),
            )

    def _emit_process_kpis_util(self, t_now, util_w):
        # Iterate union of (process buckets with tools) and (process buckets that
        # received finish/rework/scrap). This makes Performance/Quality emit even
        # for processes whose tool→process map is empty (rare safety net).
        proc_keys = set(self._process_tools.keys()) | set(self._kpi_proc_finish_dq.keys())
        for proc_name in proc_keys:
            tool_ids = self._process_tools.get(proc_name, [])

            # ---- Availability (Utilization) ----
            if tool_ids:
                run_sum = sum(
                    self._kpi_unit_state_time_in_window(tid, util_w, t_now)["RUN"] for tid in tool_ids
                )
                util_denom = util_w * max(1, len(tool_ids))
                util_value = (run_sum / util_denom) if util_denom > 0 else 0.0
                self._log_kpi_snapshot(
                    "PROCESS", proc_name, "utilization", util_value,
                    window_minutes=int(util_w), numerator=run_sum, denominator=util_denom,
                )
            else:
                util_value = 0.0

            # ---- Performance = Σ standard_proc_time / Σ actual_proc_time ----
            actual_sum = self._kpi_sum_in_window(self._kpi_proc_actual_dq.get(proc_name), t_now, util_w)
            std_sum = self._kpi_sum_in_window(self._kpi_proc_standard_dq.get(proc_name), t_now, util_w)
            performance = (std_sum / actual_sum) if actual_sum > 0 else 0.0
            self._log_kpi_snapshot(
                "PROCESS", proc_name, "performance", performance,
                window_minutes=int(util_w), numerator=std_sum, denominator=actual_sum,
            )

            # ---- Quality = First-Pass Yield = (finish - rework - scrap) / finish ----
            finish_n = self._kpi_count_in_window(self._kpi_proc_finish_dq.get(proc_name), t_now, util_w)
            rework_n = self._kpi_count_in_window(self._kpi_proc_rework_dq.get(proc_name), t_now, util_w)
            scrap_n = self._kpi_count_in_window(self._kpi_proc_scrap_dq.get(proc_name), t_now, util_w)
            if finish_n > 0:
                quality_raw = (finish_n - rework_n - scrap_n) / finish_n
                quality = max(0.0, min(1.0, quality_raw))
            else:
                quality = 0.0
            self._log_kpi_snapshot(
                "PROCESS", proc_name, "quality", quality,
                window_minutes=int(util_w),
                numerator=float(max(0, finish_n - rework_n - scrap_n)),
                denominator=float(finish_n),
                meta=f'{{"finish":{finish_n},"rework":{rework_n},"scrap":{scrap_n}}}',
            )

            # ---- OEE = Availability * Performance * Quality ----
            # Performance is capped at 1.0 by OEE convention (actual >= standard).
            perf_capped = min(1.0, performance) if performance > 0 else 0.0
            oee_value = util_value * perf_capped * quality
            self._log_kpi_snapshot(
                "PROCESS", proc_name, "oee_estimate", oee_value,
                window_minutes=int(util_w),
                numerator=None, denominator=None,
                meta=(
                    f'{{"availability":{util_value:.6f},'
                    f'"performance":{performance:.6f},'
                    f'"performance_capped":{perf_capped:.6f},'
                    f'"quality":{quality:.6f}}}'
                ),
            )

    def _emit_toolgroup_kpis_instant(self, t_now):
        for group_name, mg in self.machine_groups.items():
            tool_ids = mg.get("tool_ids", [])
            if not tool_ids:
                continue
            avail_count = sum(
                1 for tid in tool_ids
                if self.tools.get(tid, {}).get("op_state", "IDLE") in ("IDLE", "RUN", "SETUP")
            )
            n = max(1, len(tool_ids))
            q_sum = 0.0
            waiting = 0
            processing = 0
            for tid in tool_ids:
                td = self.tools.get(tid)
                if not td:
                    continue
                waiting += len(td["queue"])
                processing += td["resource"].count
                for evt in td["queue"]:
                    q_sum += max(0.0, t_now - getattr(evt, "enqueue_time", t_now))
            q_value = (q_sum / waiting) if waiting > 0 else 0.0
            self._log_kpi_snapshot(
                "TOOLGROUP", group_name, "available_tool_ratio", avail_count / n,
                window_minutes=None, numerator=float(avail_count), denominator=float(n),
            )
            self._log_kpi_snapshot(
                "TOOLGROUP", group_name, "wip", float(waiting + processing),
                window_minutes=None, numerator=float(waiting), denominator=float(processing),
            )
            self._log_kpi_snapshot(
                "TOOLGROUP", group_name, "q_time_min", q_value,
                window_minutes=None, numerator=q_sum, denominator=float(waiting),
            )
            self._log_kpi_snapshot(
                "TOOLGROUP", group_name, "wait_ratio", float(waiting) / float(max(1, avail_count)),
                window_minutes=None, numerator=float(waiting), denominator=float(max(1, avail_count)),
            )

    def _emit_toolgroup_kpis_util(self, t_now, util_w):
        for group_name, mg in self.machine_groups.items():
            tool_ids = mg.get("tool_ids", [])
            if not tool_ids:
                continue
            unit_utils = []
            setup_ratios = []
            for tid in tool_ids:
                bucket = self._kpi_unit_state_time_in_window(tid, util_w, t_now)
                if util_w > 0:
                    unit_utils.append(bucket["RUN"] / util_w)
                    setup_ratios.append(bucket["SETUP"] / util_w)
            n = max(1, len(tool_ids))
            self._log_kpi_snapshot(
                "TOOLGROUP", group_name, "utilization_avg",
                (sum(unit_utils) / n) if unit_utils else 0.0,
                window_minutes=int(util_w), numerator=float(sum(unit_utils)), denominator=float(n),
            )
            self._log_kpi_snapshot(
                "TOOLGROUP", group_name, "setup_ratio_avg",
                (sum(setup_ratios) / n) if setup_ratios else 0.0,
                window_minutes=int(util_w), numerator=float(sum(setup_ratios)), denominator=float(n),
            )

    def _emit_tool_kpis_instant(self, t_now):
        for tid, td in self.tools.items():
            q = td["queue"]
            q_len = float(len(q))
            processing = float(td["resource"].count)
            avg_q = 0.0
            if q_len > 0:
                avg_q = sum(max(0.0, t_now - getattr(e, "enqueue_time", t_now)) for e in q) / q_len
            self._log_kpi_snapshot(
                "TOOL", tid, "q_len", q_len,
                window_minutes=None, numerator=q_len, denominator=None,
            )
            self._log_kpi_snapshot(
                "TOOL", tid, "processing_count", processing,
                window_minutes=None, numerator=processing, denominator=None,
            )
            self._log_kpi_snapshot(
                "TOOL", tid, "avg_q_time", avg_q,
                window_minutes=None, numerator=(avg_q * q_len), denominator=q_len,
            )

    def _emit_tool_kpis_util(self, t_now, util_w):
        denom = util_w if util_w > 0 else 1.0
        # Iterate union of (live tools) and (tools that received finish/rework/scrap).
        # In practice this equals self.tools, but keep it consistent with PROCESS emit.
        tool_keys = set(self.tools.keys()) | set(self._kpi_tool_finish_dq.keys())
        for tid in tool_keys:
            bucket = self._kpi_unit_state_time_in_window(tid, util_w, t_now)
            util_value = bucket["RUN"] / denom

            # ---- Availability (utilization) — kept for back-compat ----
            self._log_kpi_snapshot(
                "TOOL", tid, "utilization", util_value,
                window_minutes=int(util_w), numerator=bucket["RUN"], denominator=denom,
            )
            self._log_kpi_snapshot(
                "TOOL", tid, "setup_ratio", bucket["SETUP"] / denom,
                window_minutes=int(util_w), numerator=bucket["SETUP"], denominator=denom,
            )
            down = bucket["DOWN_PM"] + bucket["DOWN_BM"]
            self._log_kpi_snapshot(
                "TOOL", tid, "down_ratio", down / denom,
                window_minutes=int(util_w), numerator=down, denominator=denom,
            )

            # ---- Performance = Σ standard / Σ actual (window) ----
            actual_sum = self._kpi_sum_in_window(self._kpi_tool_actual_dq.get(tid), t_now, util_w)
            std_sum = self._kpi_sum_in_window(self._kpi_tool_standard_dq.get(tid), t_now, util_w)
            performance = (std_sum / actual_sum) if actual_sum > 0 else 0.0
            self._log_kpi_snapshot(
                "TOOL", tid, "performance", performance,
                window_minutes=int(util_w), numerator=std_sum, denominator=actual_sum,
            )

            # ---- Quality = First-Pass Yield = (finish - rework - scrap) / finish ----
            finish_n = self._kpi_count_in_window(self._kpi_tool_finish_dq.get(tid), t_now, util_w)
            rework_n = self._kpi_count_in_window(self._kpi_tool_rework_dq.get(tid), t_now, util_w)
            scrap_n = self._kpi_count_in_window(self._kpi_tool_scrap_dq.get(tid), t_now, util_w)
            if finish_n > 0:
                quality_raw = (finish_n - rework_n - scrap_n) / finish_n
                quality = max(0.0, min(1.0, quality_raw))
            else:
                quality = 0.0
            self._log_kpi_snapshot(
                "TOOL", tid, "quality", quality,
                window_minutes=int(util_w),
                numerator=float(max(0, finish_n - rework_n - scrap_n)),
                denominator=float(finish_n),
                meta=f'{{"finish":{finish_n},"rework":{rework_n},"scrap":{scrap_n}}}',
            )

            # ---- OEE = Availability × min(Performance, 1) × Quality ----
            perf_capped = min(1.0, performance) if performance > 0 else 0.0
            oee_value = util_value * perf_capped * quality
            self._log_kpi_snapshot(
                "TOOL", tid, "oee_estimate", oee_value,
                window_minutes=int(util_w),
                numerator=None, denominator=None,
                meta=(
                    f'{{"availability":{util_value:.6f},'
                    f'"performance":{performance:.6f},'
                    f'"performance_capped":{perf_capped:.6f},'
                    f'"quality":{quality:.6f}}}'
                ),
            )