"""Handoff JSON contract: inline stat rows, no CSV pointers for Agent input."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from stats.g_star_analysis import GStarAnalysisConfig, write_g_star_analysis_outputs
from stats.whatif_effect import WhatifEffectConfig, write_whatif_outputs


def test_g_star_handoff_block_inline_evidence(tmp_path: Path):
    summary = pd.DataFrame([
        {
            "toolgroup": "TG1",
            "kpi": "q_time_min",
            "in_g_star": 1,
            "direction": "greater",
            "n_base": 2,
            "n_fwd": 30,
            "mean_base": 1.0,
            "mean_fwd": 2.0,
            "delta_mean": 1.0,
            "lb_pvalue": 0.5,
            "lb_independent": 1,
            "t_stat": 2.0,
            "t_p": 0.04,
            "t_p_adj": 0.08,
            "status": "ok",
            "kpi_significant": 0,
            "anchor_tg": "TG1",
        },
    ])
    cfg = GStarAnalysisConfig(t0=100.0)
    block = write_g_star_analysis_outputs(
        tmp_path,
        summary,
        cfg=cfg,
        g_star={"TG1"},
        anchor_tg="TG1",
        n_runs=30,
    )
    assert "evidence_csv" not in block
    assert "summary_csv" not in block
    assert len(block["g_star_kpi_evidence"]) == 1
    row = block["g_star_kpi_evidence"][0]
    assert row["toolgroup"] == "TG1"
    assert row["t_p_adj"] == 0.08
    json.dumps(block, allow_nan=False)


def test_whatif_handoff_block_inline_paired_results(tmp_path: Path):
    summary = pd.DataFrame([
        {
            "level": "TOOL",
            "scope": "Diffusion_FE_120#1",
            "kpi_name": "q_len",
            "paired_n": 30,
            "mean_delta": -10.0,
            "ci_lo": -10.0,
            "ci_hi": -10.0,
            "paired_t_p": 0.0,
            "verdict": "improved",
            "nonzero_delta": 1,
        },
    ])
    cfg = WhatifEffectConfig(t0=26820.0)
    block = write_whatif_outputs(
        tmp_path,
        summary,
        cfg=cfg,
        baseline_scenario_id="FWD_BASE",
        whatif_scenario_id="FWD_WHATIF",
        paired_n=30,
    )
    assert "summary_csv" not in block
    assert "highlights" not in block
    assert len(block["whatif_paired_results"]) == 1
    row = block["whatif_paired_results"][0]
    assert row["scope"] == "Diffusion_FE_120#1"
    assert row["paired_t_p"] == 0.0
    json.dumps(block, allow_nan=False)
