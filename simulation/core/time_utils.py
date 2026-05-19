from __future__ import annotations


def epoch_to_sim_min(epoch_sec: float, anchor_epoch_sec: float) -> float:
    return (float(epoch_sec) - float(anchor_epoch_sec)) / 60.0


def sim_min_to_epoch(sim_min: float, anchor_epoch_sec: float) -> float:
    return float(anchor_epoch_sec) + (float(sim_min) * 60.0)
