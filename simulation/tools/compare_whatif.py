#!/usr/bin/env python3
"""
Compare baseline vs what-if KPI CSVs at snapshot_time ≈ T0 + horizon.

Writes whatif_compare_summary.csv and optionally inserts kpi_whatif_diff rows.
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_KPI_FILES = (
    ("FAB", "kpi_fab.csv"),
    ("TOOLGROUP", "kpi_toolgroup.csv"),
    ("TOOL", "kpi_tool.csv"),
    ("PROCESS", "kpi_process.csv"),
)

_DEFAULT_KPIS = (
    "wip", "q_time_min", "utilization", "utilization_avg",
    "wait_ratio", "available_tool_ratio", "q_len", "processing_count",
    "throughput_24h", "tat_min", "rtf", "completion_rate",
)

_SUMMARY_FIELDS = [
    "baseline_scenario_id", "whatif_scenario_id",
    "baseline_run_id", "whatif_run_id",
    "snapshot_time", "level", "scope", "kpi_name",
    "baseline_value", "whatif_value", "delta",
]


def _float(v) -> Optional[float]:
    if v is None or str(v).strip() == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _read_kpi_rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _first_run_id(rows: list[dict]) -> Optional[str]:
    for r in rows:
        rid = (r.get("run_id") or "").strip()
        if rid:
            return rid
    return None


def _filter_snapshot(
    rows: list[dict],
    target_time: float,
    tolerance: float,
) -> list[dict]:
    out = []
    for r in rows:
        t = _float(r.get("snapshot_time"))
        if t is None:
            continue
        if abs(t - target_time) <= tolerance:
            out.append(r)
    if out:
        return out
    # fallback: nearest snapshot to target
    best: list[tuple[float, dict]] = []
    for r in rows:
        t = _float(r.get("snapshot_time"))
        if t is None:
            continue
        best.append((abs(t - target_time), r))
    if not best:
        return []
    best.sort(key=lambda x: x[0])
    nearest_t = _float(best[0][1].get("snapshot_time"))
    return [r for d, r in best if _float(r.get("snapshot_time")) == nearest_t and d == best[0][0]]


def _index_rows(
    rows: Iterable[dict],
    kpi_names: Optional[set[str]],
) -> Dict[Tuple[str, str], dict]:
    idx: Dict[Tuple[str, str], dict] = {}
    for r in rows:
        name = (r.get("kpi_name") or "").strip()
        if kpi_names and name and name not in kpi_names:
            continue
        scope = (r.get("scope") or "*").strip()
        key = (scope, name)
        val = _float(r.get("value"))
        if val is None:
            continue
        idx[key] = r
    return idx


def compare_dirs(
    baseline_csv_dir: Path,
    whatif_csv_dir: Path,
    t0: float,
    horizon: float,
    tolerance: float = 1.0,
    kpi_names: Optional[List[str]] = None,
) -> tuple[list[dict], float, Optional[str], Optional[str]]:
    target = float(t0) + float(horizon)
    kpi_filter = set(kpi_names) if kpi_names else None
    summary: list[dict] = []
    baseline_run: Optional[str] = None
    whatif_run: Optional[str] = None

    for level, fname in _KPI_FILES:
        b_rows = _read_kpi_rows(baseline_csv_dir / fname)
        w_rows = _read_kpi_rows(whatif_csv_dir / fname)
        if not baseline_run:
            baseline_run = _first_run_id(b_rows)
        if not whatif_run:
            whatif_run = _first_run_id(w_rows)
        b_at = _filter_snapshot(b_rows, target, tolerance)
        w_at = _filter_snapshot(w_rows, target, tolerance)
        b_idx = _index_rows(b_at, kpi_filter)
        w_idx = _index_rows(w_at, kpi_filter)
        for key in sorted(set(b_idx) | set(w_idx)):
            scope, kpi_name = key
            bv = _float(b_idx.get(key, {}).get("value"))
            wv = _float(w_idx.get(key, {}).get("value"))
            delta = None
            if bv is not None and wv is not None:
                delta = wv - bv
            summary.append({
                "level": level,
                "scope": scope,
                "kpi_name": kpi_name,
                "baseline_value": bv,
                "whatif_value": wv,
                "delta": delta,
                "snapshot_time": target,
            })
    return summary, target, baseline_run, whatif_run


def _write_summary(path: Path, rows: list[dict], meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = _SUMMARY_FIELDS
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            out = {**meta, **r}
            for k in ("baseline_value", "whatif_value", "delta"):
                v = out.get(k)
                out[k] = "" if v is None else v
            w.writerow({k: out.get(k, "") for k in fields})


def _insert_db(rows: list[dict], meta: dict, snapshot_time: float) -> int:
    from database import SessionLocal
    from models import KpiWhatifDiff

    whatif_run_id = meta.get("whatif_run_id")
    if not whatif_run_id:
        raise ValueError("--whatif-run-id required for --insert-db")
    db = SessionLocal()
    n = 0
    try:
        for r in rows:
            if r.get("delta") is None and r.get("baseline_value") is None and r.get("whatif_value") is None:
                continue
            db.add(KpiWhatifDiff(
                whatif_scenario_id=meta["whatif_scenario_id"],
                baseline_scenario_id=meta.get("baseline_scenario_id"),
                baseline_run_id=meta.get("baseline_run_id"),
                whatif_run_id=whatif_run_id,
                level=r["level"],
                scope=r["scope"],
                kpi_name=r["kpi_name"],
                snapshot_time=snapshot_time,
                baseline_value=r.get("baseline_value"),
                whatif_value=r.get("whatif_value"),
                delta=r.get("delta"),
                computed_at=datetime.utcnow(),
            ))
            n += 1
        db.commit()
        return n
    finally:
        db.close()


def main() -> int:
    p = argparse.ArgumentParser(description="Compare baseline vs what-if KPI CSVs at T0+H")
    p.add_argument("--baseline-csv-dir", type=Path, required=True)
    p.add_argument("--whatif-csv-dir", type=Path, required=True)
    p.add_argument("--t0", type=float, required=True)
    p.add_argument("--horizon", type=float, required=True)
    p.add_argument("--tolerance", type=float, default=1.0, help="Minutes around T0+H for snapshot match")
    p.add_argument("--baseline-scenario-id", required=True)
    p.add_argument("--whatif-scenario-id", required=True)
    p.add_argument("--baseline-run-id", default="")
    p.add_argument("--whatif-run-id", default="")
    p.add_argument("--out", type=Path, default=None, help="Summary CSV (default: whatif_compare_summary.csv in cwd)")
    p.add_argument("--kpi-names", default="", help="Comma-separated filter; default compares all KPIs present")
    p.add_argument("--insert-db", action="store_true")
    args = p.parse_args()

    kpi_list = [x.strip() for x in args.kpi_names.split(",") if x.strip()] or None
    summary, snap_t, b_run, w_run = compare_dirs(
        args.baseline_csv_dir.resolve(),
        args.whatif_csv_dir.resolve(),
        args.t0,
        args.horizon,
        args.tolerance,
        kpi_list,
    )
    meta = {
        "baseline_scenario_id": args.baseline_scenario_id,
        "whatif_scenario_id": args.whatif_scenario_id,
        "baseline_run_id": (args.baseline_run_id or b_run or ""),
        "whatif_run_id": (args.whatif_run_id or w_run or ""),
        "snapshot_time": snap_t,
    }
    out_path = args.out or Path("whatif_compare_summary.csv")
    _write_summary(out_path, summary, meta)
    print(f"Wrote {len(summary)} KPI rows @ snapshot_time≈{snap_t} -> {out_path}")

    if args.insert_db:
        if not meta["whatif_run_id"]:
            print("X --whatif-run-id required for --insert-db", file=sys.stderr)
            return 1
        n = _insert_db(summary, meta, snap_t)
        print(f"Inserted {n} rows into kpi_whatif_diff")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
