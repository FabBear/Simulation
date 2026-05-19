from types import SimpleNamespace

from fab_env import FabEnv


class StubSetupMgr:
    def get_setup_time(self, current_setup, next_setup):
        return 0.0

    def min_run_len(self, setup_name):
        return 0


def test_ltl_lock_forces_single_tool_candidate():
    env = FabEnv()
    env.setup_mgr = StubSetupMgr()
    env.machine_groups = {"Litho": {"tool_ids": ["Litho#1", "Litho#2"]}}
    env.tools = {
        "Litho#1": {"queue": [], "resource": SimpleNamespace(count=1), "current_setup": None, "setup_run_count": 0},
        "Litho#2": {"queue": [], "resource": SimpleNamespace(count=0), "current_setup": None, "setup_run_count": 0},
    }
    env.lot_ltl_lock["LOT_A"][100] = "Litho#1"
    step = SimpleNamespace(ltl_dedication_step=100, setup_id=None)

    candidates = env._resolve_tool_candidates("LOT_A", step, "Litho")
    assert candidates == ["Litho#1"]


def test_choose_tool_prefers_idle_when_no_ltl_lock():
    env = FabEnv()
    env.setup_mgr = StubSetupMgr()
    env.machine_groups = {"Etch": {"tool_ids": ["Etch#1", "Etch#2"]}}
    env.tools = {
        "Etch#1": {"queue": [1, 2], "resource": SimpleNamespace(count=1), "current_setup": None, "setup_run_count": 0, "toolgroup": SimpleNamespace(ranking_1=None, ranking_2=None, ranking_3=None)},
        "Etch#2": {"queue": [], "resource": SimpleNamespace(count=0), "current_setup": None, "setup_run_count": 0, "toolgroup": SimpleNamespace(ranking_1=None, ranking_2=None, ranking_3=None)},
    }
    step = SimpleNamespace(ltl_dedication_step=None, setup_id=None)

    chosen = env._choose_tool_for_lot("LOT_B", step, "Etch", "Product_X")
    assert chosen == "Etch#2"
