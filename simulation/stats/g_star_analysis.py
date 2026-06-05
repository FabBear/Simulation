"""Pipeline A: G* KPI root-cause analysis — historical 2h-diff vs FORWARD t-test."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

import csv as _csv

from stats.common import RunMeta, read_kpi_toolgroup_wide

try:
    from scipy.stats import ttest_ind
except ImportError as _e:  # pragma: no cover
    raise ImportError(
        "scipy is required for g_star_analysis t-test; pip install scipy"
    ) from _e

try:
    from statsmodels.stats.diagnostic import acorr_ljungbox
    from statsmodels.stats.multitest import multipletests
except ImportError as _e:  # pragma: no cover
    raise ImportError(
        "statsmodels is required for Ljung-Box test and BH-FDR correction; "
        "pip install statsmodels"
    ) from _e


_KPI_DIRECTION: dict[str, str] = {
    "q_time_min": "greater",
    "wait_ratio": "greater",
    "wip": "greater",
    "utilization_avg": "greater",
    "available_tool_ratio": "less",
}

_DEFAULT_KPIS: tuple[str, ...] = (
    "q_time_min",
    "wait_ratio",
    "wip",
    "available_tool_ratio",
    "utilization_avg",
)

_EVIDENCE_COLUMNS = [
    "toolgroup", "kpi", "direction",
    "n_base", "n_fwd", "mean_base", "mean_fwd", "delta_mean",
    "lb_pvalue", "lb_independent", "t_stat", "t_p", "t_p_adj",
    "status", "kpi_significant", "anchor_tg",
]


@dataclass
class GStarAnalysisConfig:
    t0: float
    horizon: float = 120.0
    tolerance: float = 1.0
    alpha: float = 0.05
    independence_alpha: float = 0.01
    lb_lags: int = 10
    n_diff: int = 30
    multipletest: str = "fdr_bh"
    kpis: tuple[str, ...] = _DEFAULT_KPIS
    analysis_rule: str = "ttest_g_star_analysis"


def _kpi_val(wide: pd.DataFrame, tg: str, kpi: str) -> Optional[float]:
    if wide.empty or kpi not in wide.columns:
        return None
    rows = wide[wide["toolgroup"].astype(str) == tg]
    if rows.empty:
        return None
    v = rows.iloc[0].get(kpi)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _load_baseline_kpi_cache(
    baseline_csv_dir: Path,
    tgs: list[str],
    kpis: tuple[str, ...],
    t0: float,
    horizon: float,
    n_diff: int,
    tolerance: float,
) -> dict[tuple[str, str], list[Optional[float]]]:
    snap_times = [t0 - j * horizon for j in range(n_diff + 1)]
    tg_set = set(tgs)
    kpi_set = set(kpis)

    cache: dict[tuple[str, str], list[Optional[float]]] = {
        (tg, kpi): [None] * (n_diff + 1)
        for tg in tgs
        for kpi in kpis
    }

    tg_csv = baseline_csv_dir / "kpi_toolgroup.csv"
    if not tg_csv.is_file():
        return cache

    raw: dict[tuple[int, str, str], float] = {}

    with tg_csv.open(encoding="utf-8", newline="") as f:
        reader = _csv.DictReader(f)
        for row in reader:
            kpi_name = (row.get("kpi_name") or "").strip()
            if kpi_name not in kpi_set:
                continue
            scope = (row.get("scope") or row.get("toolgroup") or "").strip()
            if scope not in tg_set:
                continue
            try:
                snap_val = float(row.get("snapshot_time") or "")
            except (TypeError, ValueError):
                continue
            best_j = None
            best_dist = float("inf")
            for j, s in enumerate(snap_times):
                dist = abs(snap_val - s)
                if dist <= tolerance and dist < best_dist:
                    best_dist = dist
                    best_j = j
            if best_j is None:
                continue
            try:
                v = float(row.get("value") or "")
            except (TypeError, ValueError):
                continue
            raw[(best_j, scope, kpi_name)] = v

    for (j, tg, kpi), v in raw.items():
        cache[(tg, kpi)][j] = v

    return cache


def _analyze_g_star_row(
    tg: str,
    kpi: str,
    *,
    cfg: GStarAnalysisConfig,
    anchor: str,
    baseline_cache: dict[tuple[str, str], list[Optional[float]]],
    base_t0_vals: dict[tuple[str, str], Optional[float]],
    fwd_wide_list: list[pd.DataFrame],
) -> dict:
    direction = _KPI_DIRECTION.get(kpi, "greater")
    base_row = {
        "toolgroup": tg,
        "kpi": kpi,
        "in_g_star": 1,
        "direction": direction,
        "alpha": cfg.alpha,
        "kpi_significant": 0,
        "anchor_tg": anchor,
    }

    vals = baseline_cache.get((tg, kpi), [None] * (cfg.n_diff + 1))
    if any(v is None for v in vals):
        return {
            **base_row,
            "n_base": 0,
            "n_fwd": 0,
            "mean_base": None,
            "mean_fwd": None,
            "delta_mean": None,
            "lb_pvalue": None,
            "lb_independent": None,
            "t_stat": None,
            "t_p": None,
            "t_p_adj": None,
            "status": "insufficient_history",
        }

    delta_base = [vals[j] - vals[j + 1] for j in range(cfg.n_diff)]
    delta_base_arr = np.array(delta_base, dtype=float)

    kpi_t0 = base_t0_vals.get((tg, kpi))
    if kpi_t0 is None:
        return {
            **base_row,
            "n_base": len(delta_base),
            "n_fwd": 0,
            "mean_base": float(np.mean(delta_base_arr)),
            "mean_fwd": None,
            "delta_mean": None,
            "lb_pvalue": None,
            "lb_independent": None,
            "t_stat": None,
            "t_p": None,
            "t_p_adj": None,
            "status": "insufficient_history",
        }

    delta_fwd_list: list[float] = []
    for w in fwd_wide_list:
        v_fwd = _kpi_val(w, tg, kpi)
        if v_fwd is not None:
            delta_fwd_list.append(v_fwd - kpi_t0)

    if len(delta_fwd_list) < 2:
        return {
            **base_row,
            "n_base": len(delta_base),
            "n_fwd": len(delta_fwd_list),
            "mean_base": float(np.mean(delta_base_arr)),
            "mean_fwd": float(np.mean(delta_fwd_list)) if delta_fwd_list else None,
            "delta_mean": None,
            "lb_pvalue": None,
            "lb_independent": None,
            "t_stat": None,
            "t_p": None,
            "t_p_adj": None,
            "status": "insufficient_forward",
        }

    delta_fwd_arr = np.array(delta_fwd_list, dtype=float)

    if np.var(delta_base_arr) < 1e-12:
        lb_p = 1.0
        lb_independent = True
    else:
        lb_result = acorr_ljungbox(delta_base_arr, lags=[cfg.lb_lags], return_df=True)
        lb_p_raw = lb_result["lb_pvalue"].iloc[-1]
        lb_p = 1.0 if (lb_p_raw is None or np.isnan(float(lb_p_raw))) else float(lb_p_raw)
        lb_independent = bool(lb_p >= cfg.independence_alpha)

    res = ttest_ind(delta_fwd_arr, delta_base_arr, equal_var=False, alternative=direction)
    t_stat = float(res.statistic)
    t_p_raw = float(res.pvalue)
    t_p = 1.0 if np.isnan(t_p_raw) else t_p_raw

    mean_base = float(np.mean(delta_base_arr))
    mean_fwd = float(np.mean(delta_fwd_arr))
    status = "ok" if lb_independent else "autocorrelated"

    return {
        **base_row,
        "n_base": len(delta_base),
        "n_fwd": len(delta_fwd_list),
        "mean_base": mean_base,
        "mean_fwd": mean_fwd,
        "delta_mean": mean_fwd - mean_base,
        "lb_pvalue": lb_p,
        "lb_independent": int(lb_independent),
        "t_stat": t_stat,
        "t_p": t_p,
        "t_p_adj": None,
        "status": status,
    }


def run_g_star_analysis(
    runs: list[RunMeta],
    g_star: set[str],
    *,
    baseline_csv_dir: Path,
    anchor_tg: Optional[str] = None,
    config: Optional[GStarAnalysisConfig] = None,
) -> pd.DataFrame:
    """Run t-test based G* KPI analysis.

    Tests G* toolgroups only; non-G* rows are reference (not_in_g_star).
    Handoff always includes all G* x KPI evidence rows.
    """
    cfg = config or GStarAnalysisConfig(t0=0.0)
    baseline_csv_dir = Path(baseline_csv_dir)
    if not runs:
        raise ValueError("g_star_analysis requires at least one run")
    if not g_star:
        raise ValueError("g_star_analysis requires non-empty g_star")

    anchor = anchor_tg or sorted(g_star)[0]
    test_pool = sorted(g_star)

    t_fwd = cfg.t0 + cfg.horizon
    all_tgs: set[str] = set()
    fwd_wide_list: list[pd.DataFrame] = []
    for run in runs:
        rid = run.run_id or None
        w = read_kpi_toolgroup_wide(run.csv_dir, rid, t_fwd, cfg.tolerance)
        fwd_wide_list.append(w)
        if not w.empty and "toolgroup" in w.columns:
            all_tgs.update(w["toolgroup"].astype(str).tolist())

    print(
        f"  Loading baseline cache for {len(test_pool)} G* TGs × {len(cfg.kpis)} KPIs "
        f"× {cfg.n_diff + 1} snapshots from {baseline_csv_dir} ...",
        flush=True,
    )
    baseline_cache = _load_baseline_kpi_cache(
        baseline_csv_dir,
        test_pool,
        cfg.kpis,
        cfg.t0,
        cfg.horizon,
        cfg.n_diff,
        cfg.tolerance,
    )
    print("  Baseline cache loaded.", flush=True)

    base_t0_vals: dict[tuple[str, str], Optional[float]] = {
        (tg, kpi): baseline_cache[(tg, kpi)][0]
        for tg in test_pool
        for kpi in cfg.kpis
    }

    rows_pre: list[dict] = []
    all_t_p: list[float] = []
    row_indices_for_correction: list[int] = []

    for tg in test_pool:
        for kpi in cfg.kpis:
            row = _analyze_g_star_row(
                tg,
                kpi,
                cfg=cfg,
                anchor=anchor,
                baseline_cache=baseline_cache,
                base_t0_vals=base_t0_vals,
                fwd_wide_list=fwd_wide_list,
            )
            rows_pre.append(row)
            if row["status"] == "ok":
                row_indices_for_correction.append(len(rows_pre) - 1)
                all_t_p.append(float(row["t_p"]))

    if all_t_p:
        if cfg.multipletest == "none":
            adj_p = all_t_p
        else:
            _, adj_p_arr, *_ = multipletests(all_t_p, alpha=cfg.alpha, method=cfg.multipletest)
            adj_p = list(adj_p_arr)

        for idx_row, adj in zip(row_indices_for_correction, adj_p):
            rows_pre[idx_row]["t_p_adj"] = float(adj)
            lb_ok = rows_pre[idx_row].get("lb_independent") == 1
            rows_pre[idx_row]["kpi_significant"] = int(lb_ok and float(adj) < cfg.alpha)

    for tg in sorted(all_tgs - g_star):
        for kpi in cfg.kpis:
            rows_pre.append({
                "toolgroup": tg,
                "kpi": kpi,
                "in_g_star": 0,
                "direction": _KPI_DIRECTION.get(kpi, "greater"),
                "n_base": None,
                "n_fwd": None,
                "mean_base": None,
                "mean_fwd": None,
                "delta_mean": None,
                "lb_pvalue": None,
                "lb_independent": None,
                "t_stat": None,
                "t_p": None,
                "t_p_adj": None,
                "alpha": cfg.alpha,
                "status": "not_in_g_star",
                "kpi_significant": 0,
                "anchor_tg": anchor,
            })

    return pd.DataFrame(rows_pre)


def write_g_star_analysis_outputs(
    out_dir: Path,
    summary: pd.DataFrame,
    *,
    cfg: GStarAnalysisConfig,
    g_star: set[str],
    anchor_tg: str,
    n_runs: int,
    runs_manifest_name: str = "runs_manifest.csv",
    baseline_csv_dir: str = "sim_csv_out",
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_path = out_dir / "g_star_analysis_summary.csv"
    summary.to_csv(summary_path, index=False)

    evidence_df = summary[summary["in_g_star"] == 1].copy()
    evidence_cols = [c for c in _EVIDENCE_COLUMNS if c in evidence_df.columns]
    evidence_path = out_dir / "g_star_kpi_evidence.csv"
    evidence_df[evidence_cols].to_csv(evidence_path, index=False)

    g_star_sorted = sorted(g_star)
    fdr_n = int(
        ((summary["in_g_star"] == 1) & (summary["status"] == "ok")).sum()
    )

    return {
        "anchor_tg": anchor_tg,
        "analysis_rule": cfg.analysis_rule,
        "significance_alpha": cfg.alpha,
        "independence_test": "ljung_box",
        "independence_alpha": cfg.independence_alpha,
        "lb_lags": cfg.lb_lags,
        "n_diff_baseline": cfg.n_diff,
        "n_runs_forward": n_runs,
        "fdr_scope": "g_star_x_kpi",
        "fdr_n_hypotheses": fdr_n,
        "kpis": list(cfg.kpis),
        "multipletest": cfg.multipletest,
        "g_star_toolgroups": g_star_sorted,
        "summary_csv": summary_path.name,
        "evidence_csv": evidence_path.name,
        "baseline_csv_dir": baseline_csv_dir,
        "runs_manifest": runs_manifest_name,
    }
