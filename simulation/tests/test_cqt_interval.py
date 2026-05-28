from types import SimpleNamespace

from fab_env import FabEnv


def test_cqt_anchor_target_fields():
    step = SimpleNamespace(
        step_seq=30,
        cqt_anchor_step=30,
        cqt_target_step=31,
        cqt_start_step=31,
        cqt_limit=2.0,
        cqt_unit="hr",
    )
    env = FabEnv()
    assert env._cqt_anchor_step(step) == 30
    assert env._cqt_target_step(step) == 31


def test_cqt_timer_start_only_after_anchor_finish():
    env = FabEnv()
    env.sim_env = SimpleNamespace(now=100.0)
    step = SimpleNamespace(
        step_seq=30,
        cqt_anchor_step=30,
        cqt_target_step=31,
        cqt_limit=1.0,
        cqt_unit="min",
        cqt_start_step=31,
    )
    env._log_lot_event = lambda *a, **k: None
    env._sync_cqt_table = lambda *a, **k: None
    env._start_cqt_timer("LOT1", "P", "R", step, "TG", "TG#1")
    assert "LOT1" in env.active_cqt
    assert env.active_cqt["LOT1"]["target_step"] == 31
    assert env.active_cqt["LOT1"]["deadline_time"] == 101.0

    step_wrong = SimpleNamespace(
        step_seq=31, cqt_anchor_step=30, cqt_target_step=31, cqt_limit=1.0, cqt_unit="min",
    )
    env.active_cqt.clear()
    env._start_cqt_timer("LOT1", "P", "R", step_wrong, "TG", "TG#1")
    assert "LOT1" not in env.active_cqt
