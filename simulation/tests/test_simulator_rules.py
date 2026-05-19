import math

from fab_env import draw_distribution, SetupManager, FabEnv


def test_draw_distribution_constant():
    assert math.isclose(draw_distribution("constant", 10.0, 5.0), 10.0)


def test_setup_manager_min_run_lookup():
    class Stub:
        def __init__(self, setup_group, from_setup, to_setup, setup_time, min_run_length):
            self.setup_group = setup_group
            self.from_setup = from_setup
            self.to_setup = to_setup
            self.setup_time = setup_time
            self.min_run_length = min_run_length

    mgr = SetupManager([Stub("Implant_Gas", "A", "B", 12.0, 7)])
    assert mgr.get_setup_time("A", "B") == 12.0
    assert mgr.min_run_len("A") == 7


def test_env_reset_and_observation_shape():
    env = FabEnv()
    obs, _ = env.reset()
    assert obs.shape == env.observation_space.shape
