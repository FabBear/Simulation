"""Shared KPI snapshot, bottleneck labels, manifests for stat pipelines A/B."""
from __future__ import annotations

import csv
import json
import math
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from build_bottleneck_labels import (
    aggregate_tool_long,
    assign_bottleneck_labels,
    pivot_toolgroup_long,
)
from tools.compare_whatif import _filter_snapshot, _float, _read_kpi_rows

try:
    from scipy.stats import ttest_1samp, ttest_rel
except ImportError:  # pragma: no cover
    ttest_1samp = None  # type: ignore
    ttest_rel = None  # type: ignore


def _require_statsmodels() -> None:
    """Raise ImportError with clear message if statsmodels is not installed."""
    try:
        import statsmodels  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "statsmodels is required for g_star_analysis (Ljung-Box / BH-FDR); "
            "pip install statsmodels"
        ) from e


@dataclass
class RunMeta:
    run_index: int
    seed: int
    csv_dir: Path
    run_id: str
    scenario_id: str = ""
    status: str = "ok"


@dataclass
class PairedRunMeta:
    run_index: int
    seed: int
    baseline_csv_dir: Path
    whatif_csv_dir: Path
    baseline_run_id: str
    whatif_run_id: str = ""
    baseline_scenario_id: str = ""
    whatif_scenario_id: str = ""


@dataclass
class BottleneckThresholds:
    q_thr: float = 30.0
    w_thr: float = 1.0
    wip_thr: float = 3.0
    avail_thr: float = 0.5
    u_hi: float = 0.8
    u_lo: float = 0.5
    q_len_min: int = 2


def snapshot_targets(t0: float, horizon: float) -> tuple[float, float]:
    return float(t0), float(t0) + float(horizon)


def load_g_star(path: Path) -> set[str]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            tgs = data.get("toolgroups") or data.get("g_star") or []
        else:
            tgs = data
        return {str(x).strip() for x in tgs if str(x).strip()}
    tgs: set[str] = set()
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames and "toolgroup" in (reader.fieldnames or []):
            for row in reader:
                g = (row.get("toolgroup") or "").strip()
                if g:
                    tgs.add(g)
        else:
            f.seek(0)
            for line in f:
                g = line.strip()
                if g and not g.startswith("#"):
                    tgs.add(g)
    return tgs


def _rows_for_run_snapshot(
    csv_dir: Path,
    run_id: Optional[str],
    snapshot_time: float,
    tolerance: float,
) -> list[dict]:
    rows = _read_kpi_rows(csv_dir / "kpi_toolgroup.csv")
    if run_id:
        rows = [r for r in rows if (r.get("run_id") or "").strip() == run_id]
    return _filter_snapshot(rows, snapshot_time, tolerance)


def _wide_at_snapshot(
    csv_dir: Path,
    run_id: Optional[str],
    snapshot_time: float,
    tolerance: float,
) -> pd.DataFrame:
    """TG-wide KPI rows at one snapshot (optional tool max merge)."""
    tg_path = csv_dir / "kpi_toolgroup.csv"
    if not tg_path.is_file():
        return pd.DataFrame(columns=["toolgroup"])

    filtered = _rows_for_run_snapshot(csv_dir, run_id, snapshot_time, tolerance)
    if not filtered:
        return pd.DataFrame(columns=["toolgroup"])

    snap_vals = [_float(r.get("snapshot_time")) for r in filtered]
    snap_vals = [s for s in snap_vals if s is not None]
    if not snap_vals:
        return pd.DataFrame(columns=["toolgroup"])
    snap_use = min(snap_vals, key=lambda t: abs(t - snapshot_time))

    tmp = csv_dir / ".stats_tmp_tg.csv"
    fields = ["run_id", "snapshot_time", "scope", "kpi_name", "value", "window_minutes"]
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in filtered:
            if abs(_float(r.get("snapshot_time")) - snap_use) > 1e-6:
                continue
            w.writerow({
                "run_id": r.get("run_id", ""),
                "snapshot_time": snap_use,
                "scope": r.get("scope", ""),
                "kpi_name": r.get("kpi_name", ""),
                "value": r.get("value", ""),
                "window_minutes": r.get("window_minutes", ""),
            })

    wide = pivot_toolgroup_long(tmp)
    tmp.unlink(missing_ok=True)

    if run_id:
        wide = wide[wide["run_id"].astype(str) == str(run_id)]
    wide = wide[abs(wide["snapshot_time"].astype(float) - snap_use) < 1e-6]

    tool_path = csv_dir / "kpi_tool.csv"
    if tool_path.is_file():
        tool_rows = _read_kpi_rows(tool_path)
        if run_id:
            tool_rows = [r for r in tool_rows if (r.get("run_id") or "").strip() == run_id]
        tool_at = _filter_snapshot(tool_rows, snap_use, tolerance)
        if tool_at:
            ttmp = csv_dir / ".stats_tmp_tool.csv"
            with ttmp.open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(
                    f,
                    fieldnames=["run_id", "snapshot_time", "scope", "kpi_name", "value"],
                )
                w.writeheader()
                for r in tool_at:
                    w.writerow({
                        "run_id": r.get("run_id", ""),
                        "snapshot_time": snap_use,
                        "scope": r.get("scope", ""),
                        "kpi_name": r.get("kpi_name", ""),
                        "value": r.get("value", ""),
                    })
            try:
                tool_wide = aggregate_tool_long(ttmp)
                ttmp.unlink(missing_ok=True)
                if not tool_wide.empty:
                    tool_wide = tool_wide[
                        abs(tool_wide["snapshot_time"].astype(float) - snap_use) < 1e-6
                    ]
                    wide = wide.merge(
                        tool_wide.drop(columns=["run_id", "snapshot_time"], errors="ignore"),
                        on="toolgroup",
                        how="left",
                    )
            except Exception:
                ttmp.unlink(missing_ok=True)

    if wide.empty:
        return pd.DataFrame(columns=["toolgroup"])
    return wide


def read_kpi_toolgroup_wide(
    csv_dir: Path,
    run_id: Optional[str],
    snapshot_time: float,
    tolerance: float = 1.0,
) -> pd.DataFrame:
    wide = _wide_at_snapshot(Path(csv_dir), run_id, snapshot_time, tolerance)
    if wide.empty:
        return wide
    out = wide.copy()
    if "toolgroup" not in out.columns and "scope" in out.columns:
        out = out.rename(columns={"scope": "toolgroup"})
    return out


def bottleneck_flag(
    row: pd.Series,
    *,
    thresholds: Optional[BottleneckThresholds] = None,
) -> bool:
    th = thresholds or BottleneckThresholds()
    df = pd.DataFrame([row.to_dict()])
    label = assign_bottleneck_labels(
        df,
        q_thr=th.q_thr,
        w_thr=th.w_thr,
        wip_thr=th.wip_thr,
        avail_thr=th.avail_thr,
        u_hi=th.u_hi,
        u_lo=th.u_lo,
        q_len_min=th.q_len_min,
        use_future=False,
    )
    return bool(label.iloc[0])


def _first_run_id(csv_dir: Path) -> str:
    rows = _read_kpi_rows(csv_dir / "kpi_toolgroup.csv")
    for r in rows:
        rid = (r.get("run_id") or "").strip()
        if rid:
            return rid
    return ""


def list_run_dirs(manifest_or_parent: Path) -> list[RunMeta]:
    path = Path(manifest_or_parent)
    if path.is_dir():
        runs: list[RunMeta] = []
        for i, sub in enumerate(sorted(p for p in path.iterdir() if p.is_dir())):
            rid = _first_run_id(sub)
            runs.append(RunMeta(
                run_index=i + 1,
                seed=i + 1,
                csv_dir=sub.resolve(),
                run_id=rid,
            ))
        return runs

    if not path.is_file():
        raise FileNotFoundError(path)

    runs = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            status = (row.get("status") or "ok").strip().lower()
            if status and status != "ok":
                continue
            runs.append(RunMeta(
                run_index=int(row.get("run_index") or row.get("run") or len(runs) + 1),
                seed=int(row.get("seed") or 0),
                csv_dir=Path(row["csv_dir"]).resolve(),
                run_id=(row.get("run_id") or "").strip(),
                scenario_id=(row.get("scenario_id") or "").strip(),
                status=status or "ok",
            ))
    runs.sort(key=lambda r: r.run_index)
    return runs


def write_runs_manifest(path: Path, runs: list[RunMeta]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["run_index", "seed", "scenario_id", "run_id", "csv_dir", "status"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in runs:
            w.writerow({
                "run_index": r.run_index,
                "seed": r.seed,
                "scenario_id": r.scenario_id,
                "run_id": r.run_id,
                "csv_dir": str(r.csv_dir),
                "status": r.status,
            })


def write_paired_manifest(path: Path, pairs: list[PairedRunMeta]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "run_index", "seed",
        "baseline_csv_dir", "whatif_csv_dir",
        "baseline_run_id", "whatif_run_id",
        "baseline_scenario_id", "whatif_scenario_id",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for p in pairs:
            w.writerow({
                "run_index": p.run_index,
                "seed": p.seed,
                "baseline_csv_dir": str(p.baseline_csv_dir),
                "whatif_csv_dir": str(p.whatif_csv_dir),
                "baseline_run_id": p.baseline_run_id,
                "whatif_run_id": p.whatif_run_id,
                "baseline_scenario_id": p.baseline_scenario_id,
                "whatif_scenario_id": p.whatif_scenario_id,
            })


def list_paired_runs(manifest: Path) -> list[PairedRunMeta]:
    path = Path(manifest)
    if not path.is_file():
        raise FileNotFoundError(path)
    pairs: list[PairedRunMeta] = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pairs.append(PairedRunMeta(
                run_index=int(row.get("run_index") or len(pairs) + 1),
                seed=int(row.get("seed") or 0),
                baseline_csv_dir=Path(row["baseline_csv_dir"]).resolve(),
                whatif_csv_dir=Path(row["whatif_csv_dir"]).resolve(),
                baseline_run_id=(row.get("baseline_run_id") or "").strip(),
                whatif_run_id=(row.get("whatif_run_id") or "").strip(),
                baseline_scenario_id=(row.get("baseline_scenario_id") or "").strip(),
                whatif_scenario_id=(row.get("whatif_scenario_id") or "").strip(),
            ))
    pairs.sort(key=lambda p: p.run_index)
    return pairs


def build_paired_manifest_from_runs_manifest(
    baseline_manifest: Path,
    whatif_rows: list[dict],
) -> list[PairedRunMeta]:
    """Join Track A manifest with what-if run rows by run_index / seed."""
    baselines = list_run_dirs(baseline_manifest)
    by_index = {b.run_index: b for b in baselines}
    by_seed = {b.seed: b for b in baselines}
    pairs: list[PairedRunMeta] = []

    for row in whatif_rows:
        run_index = int(row.get("run_index") or 0)
        seed = int(row.get("seed") or row.get("run_index") or 0)
        base = by_index.get(run_index) or by_seed.get(seed)
        if base is None:
            raise ValueError(
                f"No baseline manifest row for run_index={run_index} seed={seed}"
            )
        if base.seed != seed:
            raise ValueError(
                f"seed mismatch run_index={run_index}: baseline={base.seed} whatif={seed}"
            )
        w_dir = Path(row["csv_dir"]).resolve()
        w_run = (row.get("run_id") or _first_run_id(w_dir)).strip()
        pairs.append(PairedRunMeta(
            run_index=run_index,
            seed=seed,
            baseline_csv_dir=base.csv_dir,
            whatif_csv_dir=w_dir,
            baseline_run_id=base.run_id or _first_run_id(base.csv_dir),
            whatif_run_id=w_run,
            baseline_scenario_id=base.scenario_id,
            whatif_scenario_id=(row.get("scenario_id") or "").strip(),
        ))

    if len(pairs) != len(baselines):
        warnings.warn(
            f"paired count {len(pairs)} != baseline ok count {len(baselines)}",
            stacklevel=2,
        )
    return sorted(pairs, key=lambda p: p.run_index)


def load_baseline_manifest_for_reuse(
    manifest_path: Path,
    n_runs: int,
) -> list[RunMeta]:
    runs = list_run_dirs(manifest_path)
    ok = [r for r in runs if (r.status or "ok").lower() == "ok"]
    if len(ok) < n_runs:
        raise SystemExit(
            f"reuse-baseline-manifest: need {n_runs} ok rows, found {len(ok)} in {manifest_path}"
        )
    seeds = [r.seed for r in ok[:n_runs]]
    if len(set(seeds)) != len(seeds):
        raise SystemExit("reuse-baseline-manifest: duplicate seed in manifest")
    return ok[:n_runs]


def json_scalar_for_handoff(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (float, np.floating)):
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(val, (np.integer, int)) and not isinstance(val, bool):
        return int(val)
    if isinstance(val, (np.bool_, bool)):
        return bool(val)
    if isinstance(val, str) and val.strip() == "":
        return None
    return val


def dataframe_records_for_handoff(df: pd.DataFrame, columns: list[str]) -> list[dict]:
    """DataFrame rows as JSON-serializable records for Agent handoff."""
    if df.empty:
        return []
    sub = df[columns].copy()
    records = sub.to_dict(orient="records")
    return [{k: json_scalar_for_handoff(v) for k, v in rec.items()} for rec in records]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def merge_handoff(
    g_star_analysis: Optional[dict],
    whatif: Optional[dict],
    *,
    t0: float,
    horizon: float,
    n_runs: int,
    g_star: Optional[list[str]] = None,
) -> dict:
    return {
        "version": "1.0",
        "generated_at": iso_now(),
        "t0_sim_minute": t0,
        "horizon_minutes": horizon,
        "n_runs": n_runs,
        "label_rule": "assign_bottleneck_labels / REPORT §4.3",
        "g_star_toolgroups": g_star,
        "g_star_analysis": g_star_analysis,
        "whatif": whatif,
        "agent_notes": [
            "G* = ML alarm at T0 predicting bottleneck at T0+horizon.",
            "G* analysis pool only; non-G* rows in summary are status=not_in_g_star (reference).",
            "Handoff includes ALL G* x KPI evidence regardless of kpi_significant.",
            "p-values BH-FDR corrected within G* x KPI only.",
        ],
    }
