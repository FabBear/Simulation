"""
Smoke test for FORWARD scenario plumbing in `FabEnv`.

This test does NOT touch the real database. It builds a fake `MesScenario` and
exercises only the cold-start branches that the new scenario hooks should NOT
regress, plus a few unit-level assertions on the helpers added in this task:

- offset helpers (`_sim_now_abs`, `_abs_to_rel`, `_rel_to_abs`)
- WHAT-IF action parsing for the six SSOT `action_kind`s
- `_LotReleaseLike` adapter shape matches what `_source_process` reads

The full end-to-end DB scenario run is exercised separately via:
    .venv/bin/python run_sim_forward_once.py --scenario-id <FWD_SMOKE>
once a Postgres environment is available.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_SIM = _HERE.parent
# Put this simulation dir first so we always import the FAB_BEAR `fab_env`, even
# when the legacy Simulation/SMT_2000_Simulation copy is also on sys.path.
if str(_SIM) in sys.path:
    sys.path.remove(str(_SIM))
sys.path.insert(0, str(_SIM))
# Drop any previously-imported `fab_env` (e.g., the legacy copy from another test).
for _stale in ("fab_env", "models", "database"):
    sys.modules.pop(_stale, None)

# Force a deterministic env so the engine can be imported even when no Postgres is reachable.
os.environ.setdefault("SIM_END_MINUTES", "10")

import fab_env as _fab_env_mod  # noqa: E402

# Sanity-guard: refuse to test the wrong file (helps when CWD/sys.path is confused).
assert Path(_fab_env_mod.__file__).resolve().is_relative_to(_SIM), (
    f"fab_env imported from {_fab_env_mod.__file__}, expected under {_SIM}"
)


def _make_env():
    """Return a `FabEnv` instance without calling `reset()` (skip DB)."""
    return _fab_env_mod.FabEnv()


def test_sim_clock_offset_defaults_cold_start():
    env = _make_env()
    # Cold-start (no scenario): offset stays at 0 so `_sim_now_abs == sim_env.now` exactly.
    assert env._sim_clock_offset == 0.0
    assert env._scenario_id is None
    assert env._scenario_mode is None
    assert env.hold_lots == set()
    assert env.dispatch_rule_override == {}
    assert env.force_next_tool == {}
    assert env.skip_release_ids == set()


def test_sim_now_abs_with_offset():
    env = _make_env()

    class _StubEnv:
        def __init__(self, t):
            self.now = t

    env.sim_env = _StubEnv(45.0)
    env._sim_clock_offset = 1000.0
    assert env._sim_now_abs() == 1045.0
    assert env._abs_to_rel(1200.0) == 200.0
    assert env._abs_to_rel(500.0) == 0.0  # clamped below offset
    assert env._rel_to_abs(60.0) == 1060.0


def test_apply_whatif_actions_locked_ssot_payloads():
    """Verify the engine SSOT payload contract for every supported `action_kind`."""
    env = _make_env()

    class _Action:
        def __init__(self, kind, payload, lot_id=None, tool_group=None, tool_id=None, seq=0, _id=1):
            self.action_kind = kind
            self.payload_json = payload
            self.lot_id = lot_id
            self.tool_group = tool_group
            self.tool_id = tool_id
            self.seq = seq
            self.id = _id
            self.effective_time = 0.0

    # Seed an active lot so LOT_PRIORITY has a target.
    env.active_lots_data["L1"] = {
        "lot_name": "L1", "product": "P", "rem_steps": 1, "total_steps": 1,
        "due_date": 0.0, "start_time": 0.0, "status": "Queuing", "tool_id": None,
    }

    env._apply_whatif_action(_Action("LOT_PRIORITY", {"priority": 9}, lot_id="L1"))
    assert env.active_lots_data["L1"]["priority"] == 9

    env._apply_whatif_action(_Action("LOT_HOLD", {"reason": "test"}, lot_id="L1"))
    assert "L1" in env.hold_lots

    env._apply_whatif_action(_Action("LOT_RELEASE", {}, lot_id="L1"))
    assert "L1" not in env.hold_lots

    env._apply_whatif_action(_Action(
        "DISPATCH_RULE_OVERRIDE",
        {"tool_group": "Litho_FE", "dispatch_rule": "setupavoidance superhotlot"},
    ))
    assert env.dispatch_rule_override["Litho_FE"].startswith("setupavoidance")

    env._apply_whatif_action(_Action(
        "FORCE_TOOL",
        {"tool_id": "Litho_FE#2", "once": False, "tool_group": "Litho_FE"},
        lot_id="L1",
    ))
    assert env.force_next_tool["L1"]["tool_id"] == "Litho_FE#2"
    assert env.force_next_tool["L1"]["once"] is False

    env._apply_whatif_action(_Action("SKIP_RELEASE", {"mes_lot_release_plan_id": 42}))
    assert 42 in env.skip_release_ids


def test_lot_release_like_shape_matches_source_process_reads():
    """Adapter must expose the attributes `_source_process` actually touches."""
    adapter = _fab_env_mod._LotReleaseLike(
        plan_id=1, product_name="P", route_name="R",
        start_delay=30.0, lots_per_release=2, release_interval=0.0,
        wafers_per_lot=25, priority=1, due_date_minutes=180.0,
        lot_type=None, is_super_hot_lot="no",
    )
    for attr in (
        "product_name", "route_name", "start_date", "due_date",
        "release_interval", "lots_per_release", "wafers_per_lot",
        "priority", "lot_type", "is_super_hot_lot",
    ):
        assert hasattr(adapter, attr), f"adapter missing {attr}"
    assert adapter.start_date == 30.0
    assert adapter.due_date == 180.0


def test_apply_whatif_action_accepts_json_string_payload():
    env = _make_env()

    class _Action:
        pass

    a = _Action()
    a.action_kind = "LOT_HOLD"
    a.payload_json = json.dumps({"reason": "agent_force"})
    a.lot_id = "Lx"
    a.tool_group = None
    a.tool_id = None
    a.id = 1
    env._apply_whatif_action(a)
    assert "Lx" in env.hold_lots


def test_t0_preseeded_queue_event_found_and_reused():
    """H4: T0 queue snapshot + lot process must not duplicate queue entries."""
    import simpy

    env = _make_env()
    env.sim_env = simpy.Environment()
    tool_id = "Litho_FE#1"
    env.tools[tool_id] = {
        "group": "Litho_FE",
        "queue": [],
        "resource": simpy.PriorityResource(env.sim_env, capacity=1),
        "current_setup": None,
        "toolgroup": None,
        "op_state": "IDLE",
    }
    ev = env.sim_env.event()
    ev.payload = {
        "name": "Lot_Demo_A",
        "step_seq": 100,
        "_t0_seeded": True,
        "tool_id": tool_id,
    }
    env.tools[tool_id]["queue"].append(ev)

    found = env._find_t0_preseeded_event(tool_id, "Lot_Demo_A", 100)
    assert found is ev
    assert len(env.tools[tool_id]["queue"]) == 1
