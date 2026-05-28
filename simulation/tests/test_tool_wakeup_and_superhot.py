from types import SimpleNamespace

from fab_env import FabEnv


class StubSetupMgr:
    def get_setup_time(self, current_setup, next_setup):
        if current_setup == "A" and next_setup == "B":
            return 10.0
        if current_setup == "A" and next_setup == "C":
            return 1.0
        return 0.0

    def min_run_len(self, setup_name):
        return 0


def test_choose_tool_least_setuptime_wakeup():
    env = FabEnv()
    env.setup_mgr = StubSetupMgr()
    tg = SimpleNamespace(tool_wakeup_ranking="Least Setuptime", ranking_1=None, ranking_2=None, ranking_3=None, dispatch_rule=None)
    env.machine_groups = {"Etch": {"tool_ids": ["Etch#1", "Etch#2"]}}
    env.tools = {
        "Etch#1": {
            "queue": [], "resource": SimpleNamespace(count=0), "current_setup": "B",
            "setup_run_count": 0, "toolgroup": tg, "tool_index": 0, "tool_count": 2,
        },
        "Etch#2": {
            "queue": [], "resource": SimpleNamespace(count=0), "current_setup": "A",
            "setup_run_count": 0, "toolgroup": tg, "tool_index": 1, "tool_count": 2,
        },
    }
    step = SimpleNamespace(ltl_dedication_step=None, setup_id="C")
    chosen = env._choose_tool_for_lot("LOT", step, "Etch", "Product_X")
    assert chosen == "Etch#1"  # least setup key: B->C=0 vs A->C=1.0


def test_dispatch_prefers_superhot_in_queue():
    env = FabEnv()
    env.sim_env = SimpleNamespace(now=0.0)
    env.setup_mgr = StubSetupMgr()
    tg = SimpleNamespace(
        ranking_1=None, ranking_2=None, ranking_3=None, dispatch_rule="Superhotlot",
    )
    env.tools["T#1"] = {
        "queue": [],
        "resource": SimpleNamespace(count=0),
        "current_setup": None,
        "setup_run_count": 0,
        "toolgroup": tg,
    }

    class Evt:
        def __init__(self, payload):
            self.payload = payload

    queue = [
        Evt({"super_hot": False, "priority": 99, "req_setup": None, "due_date": 1000.0, "rem_steps": 5}),
        Evt({"super_hot": True, "priority": 1, "req_setup": None, "due_date": 2000.0, "rem_steps": 5}),
    ]
    idx = env._select_dispatch_candidate("T#1", queue)
    assert idx == 1
