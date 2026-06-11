from fab_env import compute_target_lead_minutes, FabEnv


def test_target_lead_positive_matches_expected():
    start = "2018-01-01 00:00:00"
    due = "2018-01-02 00:00:00"
    assert compute_target_lead_minutes(start, due) == 1440.0


def test_target_lead_negative_is_clamped_to_zero():
    start = "2018-01-03 00:00:00"
    due = "2018-01-02 00:00:00"
    assert compute_target_lead_minutes(start, due) == 0.0


def test_sliding_due_increments_by_release_interval():
    from fab_env import calc_minutes

    base = calc_minutes("2018-02-21 15:27:08")
    interval = 51.69
    due_0 = base + 0 * interval
    due_1 = base + 1 * interval
    assert round(due_1 - due_0, 2) == interval


def test_critical_ratio_smoke_with_relative_due_date():
    env = FabEnv()
    env.sim_env = type("S", (), {"now": 100.0})()
    due_early = 200.0
    due_late = 300.0
    cr_early = env._critical_ratio(due_early, rem_steps=10)
    cr_late = env._critical_ratio(due_late, rem_steps=10)
    assert cr_early < cr_late
