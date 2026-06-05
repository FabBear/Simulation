"""Smoke: paired what-if mean delta sign."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_SIM = _HERE.parent
if str(_SIM) not in sys.path:
    sys.path.insert(0, str(_SIM))

from stats.common import PairedRunMeta
from stats.whatif_effect import WhatifEffectConfig, run_whatif_paired_analysis
from tests.test_compare_whatif import _write_kpi  # noqa: E402


def test_paired_mean_delta(tmp_path: Path):
    t0, h = 10080.0, 120.0
    target = t0 + h
    pairs = []
    for i in range(1, 4):
        b = tmp_path / f"b{i}"
        w = tmp_path / f"w{i}"
        _write_kpi(b / "kpi_toolgroup.csv", f"rb{i}", target, "TG1", "q_len", 100.0)
        _write_kpi(w / "kpi_toolgroup.csv", f"rw{i}", target, "TG1", "q_len", 90.0)
        pairs.append(PairedRunMeta(
            i, i, b, w, f"rb{i}", f"rw{i}",
        ))
    cfg = WhatifEffectConfig(t0=t0, horizon=h, kpi_names=["q_len"])
    summary = run_whatif_paired_analysis(
        pairs,
        config=cfg,
        baseline_scenario_id="B",
        whatif_scenario_id="W",
    )
    row = summary[(summary["scope"] == "TG1") & (summary["kpi_name"] == "q_len")].iloc[0]
    assert row["mean_delta"] == pytest.approx(-10.0)
    assert row["verdict"] == "improved"
