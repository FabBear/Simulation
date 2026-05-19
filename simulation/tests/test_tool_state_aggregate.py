"""Unit tests for tool-group aggregate state (no DB / no simpy run)."""

import unittest

from fab_env import FabEnv


class TestToolStateAggregate(unittest.TestCase):
    def test_count_and_representative_run_over_idle(self):
        env = FabEnv.__new__(FabEnv)
        env.machine_groups = {"DE_BE_11": {"tool_ids": ["DE_BE_11#1", "DE_BE_11#2", "DE_BE_11#3"]}}
        env.tools = {
            "DE_BE_11#1": {"op_state": "IDLE"},
            "DE_BE_11#2": {"op_state": "RUN"},
            "DE_BE_11#3": {"op_state": "IDLE"},
        }
        c = env._count_op_states_for_group("DE_BE_11")
        self.assertEqual(c["IDLE"], 2)
        self.assertEqual(c["RUN"], 1)
        self.assertEqual(env._representative_group_state(c), "RUN")

    def test_representative_down_pm_over_run(self):
        env = FabEnv.__new__(FabEnv)
        env.machine_groups = {"G": {"tool_ids": ["G#1", "G#2"]}}
        env.tools = {
            "G#1": {"op_state": "RUN"},
            "G#2": {"op_state": "DOWN_PM"},
        }
        c = env._count_op_states_for_group("G")
        self.assertEqual(env._representative_group_state(c), "DOWN_PM")

    def test_representative_down_bm_highest(self):
        env = FabEnv.__new__(FabEnv)
        env.machine_groups = {"G": {"tool_ids": ["G#1", "G#2"]}}
        env.tools = {
            "G#1": {"op_state": "DOWN_PM"},
            "G#2": {"op_state": "DOWN_BM"},
        }
        c = env._count_op_states_for_group("G")
        self.assertEqual(env._representative_group_state(c), "DOWN_BM")

    def test_unknown_op_state_buckets_as_idle(self):
        env = FabEnv.__new__(FabEnv)
        env.machine_groups = {"G": {"tool_ids": ["G#1"]}}
        env.tools = {"G#1": {"op_state": "WEIRD"}}
        c = env._count_op_states_for_group("G")
        self.assertEqual(c["IDLE"], 1)


if __name__ == "__main__":
    unittest.main()
