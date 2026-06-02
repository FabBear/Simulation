"""Tests for SET_SUPER_HOT what-if action."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import simpy

_HERE = Path(__file__).resolve().parent
_SIM = _HERE.parent
if str(_SIM) in sys.path:
    sys.path.remove(str(_SIM))
sys.path.insert(0, str(_SIM))
for _stale in ("fab_env",):
    sys.modules.pop(_stale, None)

os.environ.setdefault("SIM_END_MINUTES", "10")

import fab_env as fe  # noqa: E402


class _StubSetupMgr:
    def get_setup_time(self, _curr, _desired):
        return 0.0

    def min_run_len(self, _setup):
        return 0


def _make_env_with_queue(lot_id: str = "L_HOT", super_hot: bool = False):
    env = fe.FabEnv()
    env.sim_env = simpy.Environment()
    env.setup_mgr = _StubSetupMgr()
    tool_id = "TG#1"
    tg_row = type("TG", (), {"ranking_1": None, "ranking_2": None, "ranking_3": None})()
    env.tools[tool_id] = {
        "group": "TG",
        "queue": [],
        "resource": simpy.Resource(env.sim_env, capacity=1),
        "current_setup": None,
        "toolgroup": tg_row,
        "op_state": "IDLE",
        "setup_run_count": 0,
    }
    env.machine_groups["TG"] = {"tool_ids": [tool_id], "dispatch_rule": "fifo"}
    ev = env.sim_env.event()
    ev.enqueue_time = 0.0
    ev.payload = {
        "name": lot_id,
        "priority": 0,
        "super_hot": super_hot,
        "enqueue_time": 0.0,
        "due_date": 100.0,
        "rem_steps": 1,
        "req_setup": "S1",
    }
    env.tools[tool_id]["queue"].append(ev)
    env.active_lots_data[lot_id] = {
        "lot_name": lot_id, "status": "Queuing", "tool_id": tool_id,
    }
    return env, tool_id, ev


class _Action:
    def __init__(self, kind, payload, lot_id=None, _id=1):
        self.action_kind = kind
        self.payload_json = payload
        self.lot_id = lot_id
        self.tool_group = None
        self.tool_id = None
        self.id = _id
        self.effective_time = 0.0
        self.step_seq = None


def test_set_super_hot_updates_queue_payload():
    env, _tid, ev = _make_env_with_queue(super_hot=False)
    env._apply_whatif_action(_Action("SET_SUPER_HOT", {"super_hot": True}, lot_id="L_HOT"))
    assert ev.payload["super_hot"] is True
    assert env.active_lots_data["L_HOT"]["super_hot"] is True


def test_set_super_hot_affects_dispatch_ranking():
    env, tool_id, _ = _make_env_with_queue(lot_id="L_COLD", super_hot=False)
    ev_hot = env.sim_env.event()
    ev_hot.enqueue_time = 1.0
    ev_hot.payload = {
        "name": "L_SUPER",
        "priority": 0,
        "super_hot": False,
        "enqueue_time": 1.0,
        "due_date": 50.0,
        "rem_steps": 1,
        "req_setup": "S1",
    }
    env.tools[tool_id]["queue"].append(ev_hot)

    env._apply_whatif_action(_Action("SET_SUPER_HOT", {"super_hot": True}, lot_id="L_SUPER"))

    idx = env._select_dispatch_candidate(tool_id, env.tools[tool_id]["queue"])
    assert idx == 1
    assert env.tools[tool_id]["queue"][idx].payload["name"] == "L_SUPER"
