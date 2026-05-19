from main import compute_target_lead_minutes as main_target_lead
from fab_env import compute_target_lead_minutes as env_target_lead, FabEnv


def test_target_lead_positive_matches_expected():
    start = "2018-01-01 00:00:00"
    due = "2018-01-02 00:00:00"
    assert main_target_lead(start, due) == 1440.0
    assert env_target_lead(start, due) == 1440.0


def test_target_lead_negative_is_clamped_to_zero():
    start = "2018-01-03 00:00:00"
    due = "2018-01-02 00:00:00"
    assert main_target_lead(start, due) == 0.0
    assert env_target_lead(start, due) == 0.0


def test_relative_due_date_progresses_with_release_time():
    lead = main_target_lead("2018-01-01 00:00:00", "2018-01-02 00:00:00")
    release_1 = 0.0
    release_2 = 51.69
    due_1 = release_1 + lead
    due_2 = release_2 + lead
    assert due_2 > due_1
    assert round(due_2 - due_1, 2) == 51.69


def test_critical_ratio_smoke_with_relative_due_date():
    env = FabEnv()
    env.sim_env = type("S", (), {"now": 100.0})()
    due_early = 200.0
    due_late = 300.0
    cr_early = env._critical_ratio(due_early, rem_steps=10)
    cr_late = env._critical_ratio(due_late, rem_steps=10)
    assert cr_early < cr_late
