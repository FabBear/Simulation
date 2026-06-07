"""Pipeline B: paired what-if effect (paired t) across N seed-matched runs."""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

from stats.common import PairedRunMeta, snapshot_targets, ttest_1samp, ttest_rel
from tools.compare_whatif import compare_dirs

_PRIMARY_KPIS = frozenset({
    "q_len", "q_time_min", "wait_ratio", "wip", "utilization_avg",
})


@dataclass
class WhatifEffectConfig:
    t0: float
    horizon: float = 120.0
    tolerance: float = 1.0
    level: str = "L3"
    kpi_names: Optional[list[str]] = None
    focus_scopes: Optional[list[str]] = None
    eps: float = 1e-6


def _verdict(mean_d: float) -> str:
    if mean_d < -1e-9:
        return "improved"
    if mean_d > 1e-9:
        return "worsened"
    return "unchanged"


def run_whatif_paired_analysis(
    pairs: list[PairedRunMeta],
    *,
    config: WhatifEffectConfig,
    baseline_scenario_id: str,
    whatif_scenario_id: str,
) -> pd.DataFrame:
    if not pairs:
        raise ValueError("whatif paired analysis requires at least one pair")

    per_key: dict[tuple[str, str, str], list[float]] = {}
    b_vals: dict[tuple[str, str, str], list[float]] = {}
    w_vals: dict[tuple[str, str, str], list[float]] = {}

    for pair in pairs:
        summary, _, b_run, w_run = compare_dirs(
            pair.baseline_csv_dir,
            pair.whatif_csv_dir,
            config.t0,
            config.horizon,
            config.tolerance,
            config.kpi_names,
        )
        for row in summary:
            level = row["level"]
            scope = row["scope"]
            kpi = row["kpi_name"]
            if config.kpi_names is None and kpi not in _PRIMARY_KPIS:
                if level != "TOOLGROUP":
                    continue
            if config.focus_scopes and scope not in config.focus_scopes:
                continue
            key = (level, scope, kpi)
            d = row.get("delta")
            if d is None:
                continue
            per_key.setdefault(key, []).append(float(d))
            bv = row.get("baseline_value")
            wv = row.get("whatif_value")
            if bv is not None:
                b_vals.setdefault(key, []).append(float(bv))
            if wv is not None:
                w_vals.setdefault(key, []).append(float(wv))

    rows = []
    for key, deltas in sorted(per_key.items()):
        level, scope, kpi = key
        mean_d = sum(deltas) / len(deltas)
        n = len(deltas)
        se = (sum((x - mean_d) ** 2 for x in deltas) / max(n - 1, 1)) ** 0.5 if n > 1 else 0.0
        ci_lo, ci_hi = mean_d, mean_d
        p_val = None
        if config.level == "L3" and n >= 2:
            if ttest_1samp is not None:
                res = ttest_1samp(deltas, popmean=0.0)
                p_val = float(res.pvalue)
                if n > 1 and se > 0:
                    try:
                        from scipy.stats import t as student_t
                        tcrit = float(student_t.ppf(0.975, n - 1))
                        ci_lo = mean_d - tcrit * se / (n ** 0.5)
                        ci_hi = mean_d + tcrit * se / (n ** 0.5)
                    except ImportError:
                        pass
            elif ttest_rel is not None and key in b_vals and key in w_vals:
                if len(b_vals[key]) == len(w_vals[key]) == n:
                    p_val = float(ttest_rel(w_vals[key], b_vals[key]).pvalue)
        elif config.level == "L3" and ttest_1samp is None:
            warnings.warn("scipy missing: paired t skipped", stacklevel=2)

        rows.append({
            "level": level,
            "scope": scope,
            "kpi_name": kpi,
            "paired_n": n,
            "mean_delta": round(mean_d, 6),
            "ci_lo": round(ci_lo, 6),
            "ci_hi": round(ci_hi, 6),
            "paired_t_p": round(p_val, 6) if p_val is not None else "",
            "verdict": _verdict(mean_d),
            "nonzero_delta": int(abs(mean_d) > config.eps),
        })

    return pd.DataFrame(rows)


def highlights_from_summary(
    summary: pd.DataFrame,
    *,
    focus_scopes: Optional[list[str]] = None,
    max_rows: int = 20,
) -> list[dict]:
    df = summary.copy()
    if focus_scopes:
        df = df[df["scope"].isin(focus_scopes)]
    if df.empty:
        return []
    df = df.sort_values(by="mean_delta", key=lambda s: s.abs())
    out = []
    for _, row in df.head(max_rows).iterrows():
        ci_lo = row.get("ci_lo", "")
        ci_hi = row.get("ci_hi", "")
        out.append({
            "scope": row["scope"],
            "kpi_name": row["kpi_name"],
            "mean_delta": float(row["mean_delta"]),
            "ci_95": [float(ci_lo), float(ci_hi)] if ci_lo != "" else [],
            "paired_t_p": float(row["paired_t_p"]) if row.get("paired_t_p") != "" else None,
            "verdict": row["verdict"],
        })
    return out


def write_whatif_outputs(
    out_dir: Path,
    summary: pd.DataFrame,
    *,
    cfg: WhatifEffectConfig,
    baseline_scenario_id: str,
    whatif_scenario_id: str,
    paired_n: int,
    paired_manifest_name: str = "paired_manifest.csv",
    baseline_manifest_name: str = "runs_manifest.csv",
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "whatif_paired_summary.csv"
    summary.to_csv(path, index=False)
    hl = highlights_from_summary(summary, focus_scopes=cfg.focus_scopes)
    return {
        "baseline_scenario_id": baseline_scenario_id,
        "whatif_scenario_id": whatif_scenario_id,
        "paired_n": paired_n,
        "highlights": hl,
        "summary_csv": path.name,
        "paired_manifest": paired_manifest_name,
        "baseline_reused_from": baseline_manifest_name,
        "level": cfg.level,
    }
