"""Smoke tests: G* KPI analysis (historical 2h-diff vs FORWARD)."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from unittest import mock

import numpy as np
import pytest

_HERE = Path(__file__).resolve().parent
_SIM = _HERE.parent
if str(_SIM) not in sys.path:
    sys.path.insert(0, str(_SIM))

from stats.common import RunMeta
from stats.g_star_analysis import (
    GStarAnalysisConfig,
    run_g_star_analysis,
    write_g_star_analysis_outputs,
)

T0 = 26820.0
H = 120.0


def _write_tg_row(
    path: Path,
    run_id: str,
    snap: float,
    tg: str,
    *,
    q_time: float = 0.0,
    wait: float = 0.0,
    wip: float = 0.0,
    avail: float = 1.0,
    util: float = 0.0,
):
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.is_file()
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["run_id", "snapshot_time", "scope", "kpi_name", "value", "window_minutes"],
        )
        if new:
            w.writeheader()
        for kpi, val in [
            ("q_time_min", q_time),
            ("wait_ratio", wait),
            ("wip", wip),
            ("available_tool_ratio", avail),
            ("utilization_avg", util),
        ]:
            w.writerow({
                "run_id": run_id,
                "snapshot_time": snap,
                "scope": tg,
                "kpi_name": kpi,
                "value": val,
                "window_minutes": "",
            })


def _make_baseline_dir(
    tmp_path: Path,
    tgs: list[str],
    *,
    t0: float = T0,
    horizon: float = H,
    n_diff: int = 30,
    kpi_at: dict | None = None,
) -> Path:
    base_dir = tmp_path / "baseline"
    kpi_at = kpi_at or {}
    for j in range(n_diff + 1):
        snap = t0 - j * horizon
        for tg in tgs:
            _write_tg_row(
                base_dir / "kpi_toolgroup.csv",
                run_id="base",
                snap=snap,
                tg=tg,
                q_time=kpi_at.get((tg, "q_time_min", snap), 0.0),
                wait=kpi_at.get((tg, "wait_ratio", snap), 0.0),
                wip=kpi_at.get((tg, "wip", snap), 0.0),
                avail=kpi_at.get((tg, "available_tool_ratio", snap), 1.0),
                util=kpi_at.get((tg, "utilization_avg", snap), 0.0),
            )
    return base_dir


def _make_fwd_run(
    tmp_path: Path,
    run_idx: int,
    tgs: list[str],
    *,
    t_fwd: float = T0 + H,
    kpi_at_fwd: dict | None = None,
) -> RunMeta:
    kpi_at_fwd = kpi_at_fwd or {}
    run_dir = tmp_path / f"fwd_{run_idx}"
    rid = f"run_{run_idx}"
    for tg in tgs:
        _write_tg_row(
            run_dir / "kpi_toolgroup.csv",
            run_id=rid,
            snap=t_fwd,
            tg=tg,
            q_time=kpi_at_fwd.get((tg, "q_time_min"), 0.0),
            wait=kpi_at_fwd.get((tg, "wait_ratio"), 0.0),
            wip=kpi_at_fwd.get((tg, "wip"), 0.0),
            avail=kpi_at_fwd.get((tg, "available_tool_ratio"), 1.0),
            util=kpi_at_fwd.get((tg, "utilization_avg"), 0.0),
        )
    return RunMeta(run_idx, run_idx, run_dir, rid)


def test_g_star_only_tested(tmp_path: Path):
    tgs = ["GStar_TG", "Other_TG"]
    g_star = {"GStar_TG"}

    kpi_at = {(tg, "q_time_min", T0 - j * H): 5.0 for tg in tgs for j in range(31)}
    base_dir = _make_baseline_dir(tmp_path, list(g_star), kpi_at=kpi_at)

    rng = np.random.default_rng(42)
    fwd_runs = [
        _make_fwd_run(
            tmp_path,
            i,
            tgs,
            kpi_at_fwd={
                ("GStar_TG", "q_time_min"): 80.0 + float(rng.normal(0, 2)),
                ("Other_TG", "q_time_min"): 5.0,
            },
        )
        for i in range(1, 31)
    ]

    summary = run_g_star_analysis(
        fwd_runs, g_star, baseline_csv_dir=base_dir,
        config=GStarAnalysisConfig(t0=T0, horizon=H, n_diff=30),
    )
    tested = summary[summary["status"] != "not_in_g_star"]
    assert set(tested["toolgroup"].unique()) == {"GStar_TG"}
    ref = summary[summary["status"] == "not_in_g_star"]
    assert (ref["toolgroup"] == "Other_TG").all()
    assert ref["t_p"].isna().all()


def test_non_g_star_reference_rows(tmp_path: Path):
    tgs = ["GStar_TG", "Ref_TG"]
    g_star = {"GStar_TG"}
    base_dir = _make_baseline_dir(tmp_path, list(g_star))
    fwd_runs = [_make_fwd_run(tmp_path, i, tgs) for i in range(1, 6)]

    summary = run_g_star_analysis(
        fwd_runs, g_star, baseline_csv_dir=base_dir,
        config=GStarAnalysisConfig(t0=T0, horizon=H, n_diff=30),
    )
    ref = summary[(summary["toolgroup"] == "Ref_TG") & (summary["kpi"] == "q_time_min")].iloc[0]
    assert ref["status"] == "not_in_g_star"
    assert ref["in_g_star"] == 0
    assert ref["t_p"] is None or (isinstance(ref["t_p"], float) and np.isnan(ref["t_p"]))


def test_fdr_scope_g_star_only(tmp_path: Path):
    g_star = {"G1", "G2"}
    all_tgs = ["G1", "G2", "G3"]
    kpis = ("q_time_min", "wait_ratio")

    kpi_at = {}
    for tg in g_star:
        for j in range(31):
            snap = T0 - j * H
            kpi_at[(tg, "q_time_min", snap)] = 5.0
            kpi_at[(tg, "wait_ratio", snap)] = 0.1

    base_dir = _make_baseline_dir(tmp_path, sorted(g_star), kpi_at=kpi_at)
    rng = np.random.default_rng(1)
    fwd_runs = []
    for i in range(1, 31):
        fwd_runs.append(_make_fwd_run(
            tmp_path, i, all_tgs,
            kpi_at_fwd={
                ("G1", "q_time_min"): 50.0 + float(rng.normal(0, 1)),
                ("G2", "q_time_min"): 50.0 + float(rng.normal(0, 1)),
                ("G3", "q_time_min"): 5.0,
            },
        ))

    cfg = GStarAnalysisConfig(t0=T0, horizon=H, n_diff=30, kpis=kpis)
    summary = run_g_star_analysis(fwd_runs, g_star, baseline_csv_dir=base_dir, config=cfg)
    g_rows = summary[summary["in_g_star"] == 1]
    ok_adj = g_rows[g_rows["status"] == "ok"]["t_p_adj"].dropna()
    assert len(ok_adj) <= len(g_star) * len(kpis)
    block = write_g_star_analysis_outputs(
        tmp_path / "out", summary, cfg=cfg, g_star=g_star,
        anchor_tg="G1", n_runs=30,
    )
    assert block["fdr_scope"] == "g_star_x_kpi"
    assert block["fdr_n_hypotheses"] == len(ok_adj)


def test_evidence_includes_all_g_star_kpis(tmp_path: Path):
    g_star = {"GStar_TG"}
    base_dir = _make_baseline_dir(tmp_path, list(g_star))
    fwd_runs = [_make_fwd_run(tmp_path, i, ["GStar_TG", "Other"]) for i in range(1, 6)]

    cfg = GStarAnalysisConfig(t0=T0, horizon=H, n_diff=5)
    summary = run_g_star_analysis(fwd_runs, g_star, baseline_csv_dir=base_dir, config=cfg)
    write_g_star_analysis_outputs(
        tmp_path / "out", summary, cfg=cfg, g_star=g_star,
        anchor_tg="GStar_TG", n_runs=5,
    )
    evidence = (tmp_path / "out" / "g_star_kpi_evidence.csv").read_text()
    evidence_rows = len(evidence.strip().splitlines()) - 1
    assert evidence_rows == len(g_star) * len(cfg.kpis)


def test_ljung_box_blocks_fdr_not_evidence_row(tmp_path: Path):
    g_star = {"AutoTG"}
    kpi_at = {}
    for j in range(31):
        snap = T0 - j * H
        kpi_at[("AutoTG", "q_time_min", snap)] = float(np.sin(j * 0.4) * 50 + 50)

    base_dir = _make_baseline_dir(tmp_path, list(g_star), kpi_at=kpi_at)
    rng = np.random.default_rng(99)
    fwd_runs = [
        _make_fwd_run(
            tmp_path, i, list(g_star),
            kpi_at_fwd={("AutoTG", "q_time_min"): 500.0 + float(rng.normal(0, 5))},
        )
        for i in range(1, 31)
    ]

    summary = run_g_star_analysis(
        fwd_runs, g_star, baseline_csv_dir=base_dir,
        config=GStarAnalysisConfig(
            t0=T0, horizon=H, n_diff=30, independence_alpha=0.01, lb_lags=10,
        ),
    )
    row = summary[(summary["toolgroup"] == "AutoTG") & (summary["kpi"] == "q_time_min")].iloc[0]
    assert row["status"] == "autocorrelated"
    assert row["kpi_significant"] == 0

    write_g_star_analysis_outputs(
        tmp_path / "out", summary,
        cfg=GStarAnalysisConfig(t0=T0, horizon=H),
        g_star=g_star, anchor_tg="AutoTG", n_runs=30,
    )
    assert (tmp_path / "out" / "g_star_kpi_evidence.csv").is_file()


def test_handoff_no_candidates_key(tmp_path: Path):
    g_star = {"G1"}
    base_dir = _make_baseline_dir(tmp_path, list(g_star))
    fwd_runs = [_make_fwd_run(tmp_path, i, list(g_star)) for i in range(1, 6)]
    cfg = GStarAnalysisConfig(t0=T0, horizon=H, n_diff=5)
    summary = run_g_star_analysis(fwd_runs, g_star, baseline_csv_dir=base_dir, config=cfg)
    block = write_g_star_analysis_outputs(
        tmp_path / "out", summary, cfg=cfg, g_star=g_star,
        anchor_tg="G1", n_runs=5,
    )
    assert "candidates" not in block
    assert block["g_star_toolgroups"] == ["G1"]
    assert block["analysis_rule"] == "ttest_g_star_analysis"


def test_missing_statsmodels_raises():
    import builtins
    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "statsmodels" or name.startswith("statsmodels."):
            raise ImportError("mocked statsmodels missing")
        return real_import(name, *args, **kwargs)

    with mock.patch("builtins.__import__", side_effect=mock_import):
        with pytest.raises((ImportError, RuntimeError)):
            import importlib
            import stats.g_star_analysis as mod
            importlib.reload(mod)
