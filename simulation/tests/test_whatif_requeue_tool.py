"""Tests for REQUEUE_TOOL what-if action."""
from __future__ import annotations

import os
import sys
from pathlib import Path

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


def _two_tool_env():
    env = fe.FabEnv()
    env.sim_env = simpy.Environment()
    t1, t7 = "Litho#1", "Litho#7"
    for tid in (t1, t7):
        env.tools[tid] = {
            "group": "Litho_FE_111",
            "queue": [],
            "resource": simpy.Resource(env.sim_env, capacity=1),
            "current_setup": None,
            "toolgroup": None,
            "op_state": "IDLE",
        }
    env.machine_groups["Litho_FE_111"] = {"tool_ids": [t1, t7]}
    ev = env.sim_env.event()
    ev.enqueue_time = 10.0
    ev.payload = {
        "name": "Lot_A",
        "step_seq": 159,
        "req_setup": "S1",
        "priority": 1,
        "super_hot": False,
        "due_date": 200.0,
        "rem_steps": 3,
        "tool_id": t1,
    }
    env.tools[t1]["queue"].append(ev)
    env.active_lots_data["Lot_A"] = {
        "lot_name": "Lot_A", "status": "Queuing", "tool_id": t1,
    }
    return env, t1, t7, ev


def test_requeue_moves_lot_between_tool_queues():
    env, t1, t7, ev = _two_tool_env()
    ok = env._requeue_lot_tool(
        lot_id="Lot_A",
        tool_group="Litho_FE_111",
        to_tool_id=t7,
        from_tool_id=t1,
        step_seq=159,
    )
    assert ok is True
    assert len(env.tools[t1]["queue"]) == 0
    assert len(env.tools[t7]["queue"]) == 1
    assert env.tools[t7]["queue"][0] is ev
    assert ev.payload["tool_id"] == t7
    assert ev.enqueue_time == 0.0  # sim_env.now at start
    assert env.active_lots_data["Lot_A"]["tool_id"] == t7


def test_requeue_rejects_processing_lot():
    env, t1, t7, _ev = _two_tool_env()
    env.active_lots_data["Lot_A"]["status"] = "PROCESSING"
    ok = env._requeue_lot_tool(
        lot_id="Lot_A",
        tool_group="Litho_FE_111",
        to_tool_id=t7,
        from_tool_id=t1,
    )
    assert ok is False
    assert len(env.tools[t1]["queue"]) == 1


def test_apply_whatif_requeue_action():
    env, t1, t7, _ = _two_tool_env()

    class _Action:
        action_kind = "REQUEUE_TOOL"
        payload_json = {
            "tool_group": "Litho_FE_111",
            "from_tool_id": t1,
            "to_tool_id": t7,
            "step_seq": 159,
        }
        lot_id = "Lot_A"
        tool_group = "Litho_FE_111"
        tool_id = None
        id = 99
        effective_time = 0.0
        step_seq = None

    env._apply_whatif_action(_Action())
    assert len(env.tools[t7]["queue"]) == 1
