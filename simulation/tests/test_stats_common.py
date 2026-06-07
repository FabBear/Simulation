"""Unit tests for stats/common.py."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

_HERE = Path(__file__).resolve().parent
_SIM = _HERE.parent
if str(_SIM) not in sys.path:
    sys.path.insert(0, str(_SIM))

from stats.common import (  # noqa: E402
    BottleneckThresholds,
    RunMeta,
    build_paired_manifest_from_runs_manifest,
    bottleneck_flag,
    load_g_star,
    write_runs_manifest,
)


def test_load_g_star_json(tmp_path: Path):
    p = tmp_path / "g.json"
    p.write_text(json.dumps({"toolgroups": ["A", "B"]}), encoding="utf-8")
    assert load_g_star(p) == {"A", "B"}


def test_bottleneck_flag_high_queue():
    row = pd.Series({
        "toolgroup": "TG1",
        "q_time_min": 50.0,
        "wait_ratio": 2.0,
        "wip": 5.0,
        "available_tool_ratio": 1.0,
        "utilization_avg": 0.3,
        "max_util": 0.0,
        "max_avg_q_time": 0.0,
    })
    th = BottleneckThresholds(q_thr=30.0, w_thr=1.0, wip_thr=3.0)
    assert bottleneck_flag(row, thresholds=th) is True


def test_build_paired_manifest(tmp_path: Path):
    base_manifest = tmp_path / "runs_manifest.csv"
    write_runs_manifest(base_manifest, [
        RunMeta(1, 1, tmp_path / "b1", "rb1", "BASE_R01"),
        RunMeta(2, 2, tmp_path / "b2", "rb2", "BASE_R02"),
    ])
    pairs = build_paired_manifest_from_runs_manifest(
        base_manifest,
        [
            {"run_index": 1, "seed": 1, "csv_dir": str(tmp_path / "w1"), "run_id": "rw1"},
            {"run_index": 2, "seed": 2, "csv_dir": str(tmp_path / "w2"), "run_id": "rw2"},
        ],
    )
    assert len(pairs) == 2
    assert pairs[0].baseline_run_id == "rb1"
    assert pairs[1].seed == 2
