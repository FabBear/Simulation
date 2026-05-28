from types import SimpleNamespace

from fab_env import FabEnv


def test_pm_piece_count_increments():
    env = FabEnv()
    env._pm_piece_count = {}
    env._record_pm_pieces("T#1", 25)
    env._record_pm_pieces("T#1", 25)
    assert env._pm_piece_count["T#1"] == 50


def test_foa_stagger_formula():
    env = FabEnv()
    foa_min = 30.0
    tool_count = 4
    delays = [foa_min * (i / float(tool_count)) for i in range(tool_count)]
    assert delays[0] == 0.0
    assert delays[1] == 7.5
    assert delays[3] == 22.5
