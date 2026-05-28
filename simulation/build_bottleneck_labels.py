#!/usr/bin/env python3
"""
Build Tool-Group wide KPI table + bottleneck weak labels from sim_csv_out KPI CSVs.

Pipeline:
  1. kpi_toolgroup.csv (long) → pivot wide per (run_id, snapshot_time, toolgroup)
  2. kpi_tool.csv (long, chunked) → max(utilization), max(avg_q_time), max(q_len) per TG/time
  3. Merge → apply label rule at t + horizon (default 60 min) → write labeled CSV/parquet

Usage (from simulation/):
  .venv/bin/python build_bottleneck_labels.py --csv-dir ./sim_csv_out
  .venv/bin/python build_bottleneck_labels.py --csv-dir ./sim_csv_out --out ./sim_csv_out/tg_bottleneck_labeled.parquet

Label rule (weak oracle, see docs/REPORT_SIMULATION_KPI.md §7.2):
  y=1 if at t+H:
    (q_time_min >= Q AND (wait_ratio >= W OR wip >= N))
    OR available_tool_ratio <= A
    OR (max_util >= U_hi AND utilization_avg < U_lo)
    OR (max_avg_q_time >= Q AND wait_ratio >= W)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

TG_INSTANT_KPIS = (
    "q_time_min",
    "wait_ratio",
    "wip",
    "available_tool_ratio",
)
TG_UTIL_KPIS = ("utilization_avg", "setup_ratio_avg")
TOOL_AGG_KPIS = {
    "utilization": "max_util",
    "avg_q_time": "max_avg_q_time",
    "q_len": "max_q_len",
}


def _write_frame(df: pd.DataFrame, path: Path) -> None:
    if path.suffix == ".parquet":
        df.to_parquet(path, index=False)
    else:
        df.to_csv(path, index=False)


def tool_id_to_toolgroup(tool_id: str) -> str:
    if "#" in tool_id:
        return tool_id.rsplit("#", 1)[0]
    return tool_id


def pivot_toolgroup_long(path: Path) -> pd.DataFrame:
    """Long kpi_toolgroup → wide (run_id, snapshot_time, toolgroup)."""
    df = pd.read_csv(
        path,
        usecols=["run_id", "snapshot_time", "scope", "kpi_name", "value", "window_minutes"],
    )
    df = df.rename(columns={"scope": "toolgroup"})
    df["snapshot_time"] = df["snapshot_time"].astype(float)

    instant = df[df["window_minutes"].isna() | (df["window_minutes"] == "")]
    instant = instant[instant["kpi_name"].isin(TG_INSTANT_KPIS)]
    wide_inst = instant.pivot_table(
        index=["run_id", "snapshot_time", "toolgroup"],
        columns="kpi_name",
        values="value",
        aggfunc="first",
    ).reset_index()

    util = df[df["kpi_name"].isin(TG_UTIL_KPIS)]
    wide_util = util.pivot_table(
        index=["run_id", "snapshot_time", "toolgroup"],
        columns="kpi_name",
        values="value",
        aggfunc="first",
    ).reset_index()

    wide = wide_inst.merge(
        wide_util,
        on=["run_id", "snapshot_time", "toolgroup"],
        how="outer",
    )
    return wide


def aggregate_tool_long(path: Path, chunksize: int = 2_000_000) -> pd.DataFrame:
    """Chunk-read kpi_tool; return max metrics per (run_id, snapshot_time, toolgroup)."""
    wanted = set(TOOL_AGG_KPIS.keys())
    parts: list[pd.DataFrame] = []

    reader = pd.read_csv(
        path,
        chunksize=chunksize,
        usecols=["run_id", "snapshot_time", "scope", "kpi_name", "value"],
    )
    for i, chunk in enumerate(reader):
        chunk = chunk[chunk["kpi_name"].isin(wanted)]
        if chunk.empty:
            continue
        chunk["toolgroup"] = chunk["scope"].map(tool_id_to_toolgroup)
        chunk["snapshot_time"] = chunk["snapshot_time"].astype(float)
        g = (
            chunk.groupby(
                ["run_id", "snapshot_time", "toolgroup", "kpi_name"],
                as_index=False,
            )["value"]
            .max()
        )
        parts.append(g)
        print(f"  tool chunk {i + 1}: kept {len(chunk):,} rows → {len(g):,} groups")

    if not parts:
        return pd.DataFrame(
            columns=["run_id", "snapshot_time", "toolgroup", *TOOL_AGG_KPIS.values()]
        )

    combined = pd.concat(parts, ignore_index=True)
    combined = (
        combined.groupby(
            ["run_id", "snapshot_time", "toolgroup", "kpi_name"],
            as_index=False,
        )["value"]
        .max()
    )
    wide = combined.pivot(
        index=["run_id", "snapshot_time", "toolgroup"],
        columns="kpi_name",
        values="value",
    ).reset_index()
    wide = wide.rename(columns=TOOL_AGG_KPIS)
    return wide


def _col(df: pd.DataFrame, name: str, *, use_future: bool) -> pd.Series:
    """Prefer name_future when use_future and column exists."""
    if use_future:
        fut = f"{name}_future"
        if fut in df.columns:
            return df[fut].fillna(0)
    if name in df.columns:
        return df[name].fillna(0)
    return pd.Series(0.0, index=df.index)


def assign_bottleneck_labels(
    df: pd.DataFrame,
    *,
    q_thr: float = 30.0,
    w_thr: float = 1.0,
    wip_thr: float = 3.0,
    avail_thr: float = 0.5,
    u_hi: float = 0.8,
    u_lo: float = 0.5,
    q_len_min: int = 2,
    use_future: bool = True,
) -> pd.Series:
    """Vectorized weak label (REPORT §7.2). Default: columns at t+H (_future suffix)."""
    q = _col(df, "q_time_min", use_future=use_future)
    w = _col(df, "wait_ratio", use_future=use_future)
    wip = _col(df, "wip", use_future=use_future)
    avail = _col(df, "available_tool_ratio", use_future=use_future)
    util_avg = _col(df, "utilization_avg", use_future=use_future)
    max_util = _col(df, "max_util", use_future=use_future)
    max_q = _col(df, "max_avg_q_time", use_future=use_future)
    tg_congestion = (q >= q_thr) & ((w >= w_thr) | (wip >= wip_thr))
    low_avail = avail <= avail_thr
    hot_spot_util = (max_util >= u_hi) & (util_avg < u_lo)
    hot_spot_queue = (max_q >= q_thr) & (w >= w_thr)

    return (tg_congestion | low_avail | hot_spot_util | hot_spot_queue).astype(int)


def compute_label_row(
    row: pd.Series,
    *,
    q_thr: float,
    w_thr: float,
    wip_thr: float,
    avail_thr: float,
    u_hi: float,
    u_lo: float,
    q_len_min: int,
) -> int:
    """Row-wise label (notebooks/debug); prefer assign_bottleneck_labels for speed."""
    return int(
        assign_bottleneck_labels(
            pd.DataFrame([row]),
            q_thr=q_thr,
            w_thr=w_thr,
            wip_thr=wip_thr,
            avail_thr=avail_thr,
            u_hi=u_hi,
            u_lo=u_lo,
            q_len_min=q_len_min,
            use_future=True,
        ).iloc[0]
    )


def attach_future_labels(
    df: pd.DataFrame,
    horizon: float,
    label_cols: list[str],
) -> pd.DataFrame:
    """Self-merge: features at t, label KPIs from t+horizon (_future suffix)."""
    future = df[["run_id", "snapshot_time", "toolgroup", *label_cols]].copy()
    future = future.rename(columns={c: f"{c}_future" for c in label_cols})
    future["snapshot_time"] = future["snapshot_time"] - horizon

    merged = df.merge(
        future,
        on=["run_id", "snapshot_time", "toolgroup"],
        how="inner",
    )
    return merged


def main() -> int:
    p = argparse.ArgumentParser(description="Build TG wide table + bottleneck labels from KPI CSVs.")
    p.add_argument(
        "--csv-dir",
        type=Path,
        default=Path(os.environ.get("SIM_CSV_DIR", _ROOT / "sim_csv_out")),
        help="Directory with kpi_toolgroup.csv and kpi_tool.csv",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output path (.csv or .parquet). Default: <csv-dir>/tg_bottleneck_labeled.csv",
    )
    p.add_argument(
        "--horizon",
        type=float,
        default=float(os.environ.get("KPI_INSTANT_PERIOD_MIN", "60")),
        help="Label lookahead in sim minutes (default: KPI_INSTANT_PERIOD_MIN or 60)",
    )
    p.add_argument("--q-thr", type=float, default=30.0, help="q_time_min / max_avg_q_time threshold")
    p.add_argument("--w-thr", type=float, default=1.0, help="wait_ratio threshold")
    p.add_argument("--wip-thr", type=float, default=3.0, help="wip threshold")
    p.add_argument("--avail-thr", type=float, default=0.5, help="available_tool_ratio max (low=bad)")
    p.add_argument("--u-hi", type=float, default=0.8, help="max_util high threshold")
    p.add_argument("--u-lo", type=float, default=0.5, help="utilization_avg low threshold (hot-spot)")
    p.add_argument("--q-len-min", type=int, default=2, help="max_q_len min for hot-spot queue rule")
    p.add_argument("--chunksize", type=int, default=2_000_000, help="kpi_tool.csv read chunk size")
    p.add_argument(
        "--wide-only",
        action="store_true",
        help="Write wide table at t only (no t+H label merge)",
    )
    args = p.parse_args()

    csv_dir = args.csv_dir.resolve()
    tg_path = csv_dir / "kpi_toolgroup.csv"
    tool_path = csv_dir / "kpi_tool.csv"
    if not tg_path.is_file():
        print(f"Missing {tg_path}", file=sys.stderr)
        return 1
    if not tool_path.is_file():
        print(f"Missing {tool_path}", file=sys.stderr)
        return 1

    out = args.out
    if out is None:
        suffix = "tg_bottleneck_wide.csv" if args.wide_only else "tg_bottleneck_labeled.csv"
        out = csv_dir / suffix
    else:
        out = out.resolve()

    print(f"CSV dir: {csv_dir}")
    print("Pivot toolgroup KPIs…")
    tg_wide = pivot_toolgroup_long(tg_path)
    print(f"  TG wide rows: {len(tg_wide):,}")

    print("Aggregate tool KPIs (chunked)…")
    tool_agg = aggregate_tool_long(tool_path, chunksize=args.chunksize)
    print(f"  Tool agg rows: {len(tool_agg):,}")

    wide = tg_wide.merge(
        tool_agg,
        on=["run_id", "snapshot_time", "toolgroup"],
        how="left",
    )
    for col in TOOL_AGG_KPIS.values():
        if col in wide.columns:
            wide[col] = wide[col].fillna(0.0)

    if args.wide_only:
        _write_frame(wide, out)
        print(f"Wrote wide table: {out} ({len(wide):,} rows)")
        return 0

    label_cols = [
        "q_time_min",
        "wait_ratio",
        "wip",
        "available_tool_ratio",
        "utilization_avg",
        "max_util",
        "max_avg_q_time",
    ]
    label_cols = [c for c in label_cols if c in wide.columns]

    print(f"Attach future KPIs at t+{args.horizon}…")
    labeled = attach_future_labels(wide, args.horizon, label_cols)

    labeled["y_bottleneck"] = assign_bottleneck_labels(
        labeled,
        q_thr=args.q_thr,
        w_thr=args.w_thr,
        wip_thr=args.wip_thr,
        avail_thr=args.avail_thr,
        u_hi=args.u_hi,
        u_lo=args.u_lo,
        q_len_min=args.q_len_min,
        use_future=True,
    )

    pos = int(labeled["y_bottleneck"].sum())
    rate = 100.0 * pos / max(1, len(labeled))
    print(f"Labels: positive={pos:,} / {len(labeled):,} ({rate:.2f}%)")

    _write_frame(labeled, out)
    print(f"Wrote: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
