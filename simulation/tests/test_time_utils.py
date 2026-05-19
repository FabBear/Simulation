from core.time_utils import epoch_to_sim_min, sim_min_to_epoch


def test_epoch_sim_roundtrip():
    anchor = 1713000000.0
    epoch = 1713007200.0
    sim_min = epoch_to_sim_min(epoch, anchor)
    assert sim_min == 120.0
    assert sim_min_to_epoch(sim_min, anchor) == epoch


def test_horizon_720_is_12_hours():
    horizon_min = 720.0
    assert horizon_min == 12 * 60
