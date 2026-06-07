#!/usr/bin/env python3
"""
Train ML alarm @ t+120 (notebook-aligned features) and export G* @ T0 + audit CSV.

Usage (from simulation/):
  .venv/bin/python tools/ml_g_star_at_t0.py \\
    --train-csv-dir sim_csv_out \\
    --inference-csv-dir sim_csv_out \\
    --t0 26820 --out-dir out/ml_g_star_e2e \\
    --alarm-threshold 0.7 --snapshot-stride 10

Outputs:
  g_star_T{t0}.json
  ml_alarm_audit_t0.csv  (all TG: proba, in_g_star, bn_t0_rule, eligible_B)
  ml_shap_top.csv          (optional SHAP on alarm rows)
  ml_model.joblib          (for --infer-only reruns)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from build_bottleneck_labels import (
    TOOL_AGG_KPIS,
    aggregate_tool_long,
    assign_bottleneck_labels,
    attach_future_labels,
    pivot_toolgroup_long,
    tool_id_to_toolgroup,
)
from stats.common import BottleneckThresholds, bottleneck_flag

LOOKAHEAD_MIN = 120.0
DELTA_LAG_MIN = 120.0
DELTA_SUFFIX = "_delta_120"
KPI_COLS = [
    "available_tool_ratio",
    "q_time_min",
    "wait_ratio",
    "wip",
    "utilization_avg",
    "max_util",
    "max_avg_q_time",
]
DELTA_KPI_COLS = ["q_time_min", "wait_ratio", "wip", "max_util", "utilization_avg"]
LABEL_KPI_COLS = [
    "q_time_min",
    "wait_ratio",
    "wip",
    "available_tool_ratio",
    "utilization_avg",
    "max_util",
    "max_avg_q_time",
]
FEATURE_COLS = [
    *KPI_COLS,
    *[f"{c}{DELTA_SUFFIX}" for c in DELTA_KPI_COLS],
]


def _temporal_train_mask(df: pd.DataFrame, train_frac: float = 0.70) -> np.ndarray:
    times = np.sort(df["snapshot_time"].unique())
    cut = int(len(times) * train_frac)
    train_times = set(times[:cut])
    return df["snapshot_time"].isin(train_times).to_numpy()


def _attach_past_and_delta(wide: pd.DataFrame) -> pd.DataFrame:
    past = wide[["run_id", "snapshot_time", "toolgroup", *DELTA_KPI_COLS]].copy()
    past = past.rename(columns={c: f"{c}_lag120" for c in DELTA_KPI_COLS})
    past["snapshot_time"] = past["snapshot_time"] + DELTA_LAG_MIN
    merged = wide.merge(
        past,
        on=["run_id", "snapshot_time", "toolgroup"],
        how="left",
    )
    for c in DELTA_KPI_COLS:
        lag = f"{c}_lag120"
        if lag in merged.columns:
            merged[f"{c}{DELTA_SUFFIX}"] = merged[c].fillna(0) - merged[lag].fillna(0)
        else:
            merged[f"{c}{DELTA_SUFFIX}"] = 0.0
    return merged


def _build_raw_wide(
    csv_dir: Path,
    *,
    horizon: float,
    snapshot_stride: int,
    skip_tool_agg: bool,
    chunksize: int,
) -> pd.DataFrame:
    """Pivot toolgroup (+ optional tool agg). Stride keeps t+horizon partners for label merge."""
    csv_dir = csv_dir.resolve()
    tg_path = csv_dir / "kpi_toolgroup.csv"
    tool_path = csv_dir / "kpi_tool.csv"
    if not tg_path.is_file():
        raise FileNotFoundError(tg_path)

    print(f"Pivot toolgroup: {tg_path}")
    wide = pivot_toolgroup_long(tg_path)
    if snapshot_stride > 1:
        all_times = np.sort(wide["snapshot_time"].unique())
        time_set = set(all_times.tolist())
        keep_times: set[float] = set()
        for t in all_times[::snapshot_stride]:
            keep_times.add(float(t))
            partner = float(t) + horizon
            if partner in time_set:
                keep_times.add(partner)
        wide = wide[wide["snapshot_time"].isin(keep_times)]
        print(
            f"  snapshot stride {snapshot_stride} (+t+{horizon:.0f} partners) "
            f"-> {len(keep_times)} times"
        )

    if not skip_tool_agg and tool_path.is_file():
        print(f"Aggregate tools: {tool_path}")
        tool_agg = aggregate_tool_long(tool_path, chunksize=chunksize)
        wide = wide.merge(
            tool_agg,
            on=["run_id", "snapshot_time", "toolgroup"],
            how="left",
        )
        for col in TOOL_AGG_KPIS.values():
            if col in wide.columns:
                wide[col] = wide[col].fillna(0.0)

    return wide


def build_labeled_wide(
    csv_dir: Path,
    *,
    horizon: float,
    snapshot_stride: int,
    skip_tool_agg: bool,
    chunksize: int,
) -> pd.DataFrame:
    wide = _build_raw_wide(
        csv_dir,
        horizon=horizon,
        snapshot_stride=snapshot_stride,
        skip_tool_agg=skip_tool_agg,
        chunksize=chunksize,
    )

    if not skip_tool_agg:
        label_cols_use = LABEL_KPI_COLS
    else:
        label_cols_use = [c for c in LABEL_KPI_COLS if c in wide.columns]

    print(f"Attach labels t+{horizon}…")
    wide = attach_future_labels(wide, horizon, label_cols_use)
    if wide.empty:
        raise ValueError(
            "No labeled rows after t+t+120 merge. "
            "Use --snapshot-stride 1 or ensure KPI snapshots include t and t+120 pairs."
        )
    wide["y_bottleneck"] = assign_bottleneck_labels(wide, use_future=True).astype(int)
    wide = _attach_past_and_delta(wide)
    print(f"  labeled rows: {len(wide):,}")
    return wide


def build_feature_wide(
    csv_dir: Path,
    *,
    skip_tool_agg: bool,
    chunksize: int,
) -> pd.DataFrame:
    """Inference-only: KPI wide + delta features; no t+horizon label merge."""
    wide = _build_raw_wide(
        csv_dir,
        horizon=LOOKAHEAD_MIN,
        snapshot_stride=1,
        skip_tool_agg=skip_tool_agg,
        chunksize=chunksize,
    )
    if wide.empty:
        raise ValueError(f"No KPI rows in {csv_dir}")
    print("Attach delta features (no label merge)…")
    wide = _attach_past_and_delta(wide)
    print(f"  feature rows: {len(wide):,}")
    return wide


def _rows_near_snapshot(
    path: Path,
    target: float,
    tolerance: float,
    *,
    usecols: list[str],
    chunksize: int = 1_000_000,
) -> pd.DataFrame:
    """Chunk-read long KPI CSV; keep only rows near target snapshot (memory-safe)."""
    if not path.is_file():
        return pd.DataFrame()
    parts: list[pd.DataFrame] = []
    for chunk in pd.read_csv(path, chunksize=chunksize, usecols=usecols):
        t = chunk["snapshot_time"].astype(float)
        chunk = chunk[(t - target).abs() <= tolerance]
        if not chunk.empty:
            parts.append(chunk)
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True)


def _aggregate_tool_near_snapshot(
    path: Path,
    target: float,
    tolerance: float,
    *,
    chunksize: int = 2_000_000,
) -> pd.DataFrame:
    """max_util / max_avg_q_time / max_q_len per TG at one snapshot (chunked)."""
    wanted = set(TOOL_AGG_KPIS.keys())
    parts: list[pd.DataFrame] = []
    for chunk in pd.read_csv(
        path,
        chunksize=chunksize,
        usecols=["run_id", "snapshot_time", "scope", "kpi_name", "value"],
    ):
        chunk = chunk[chunk["kpi_name"].isin(wanted)]
        if chunk.empty:
            continue
        t = chunk["snapshot_time"].astype(float)
        chunk = chunk[(t - target).abs() <= tolerance]
        if chunk.empty:
            continue
        chunk["toolgroup"] = chunk["scope"].map(tool_id_to_toolgroup)
        g = (
            chunk.groupby(["run_id", "snapshot_time", "toolgroup", "kpi_name"], as_index=False)["value"]
            .max()
        )
        parts.append(g)
    if not parts:
        return pd.DataFrame(columns=["run_id", "snapshot_time", "toolgroup", *TOOL_AGG_KPIS.values()])
    combined = pd.concat(parts, ignore_index=True).groupby(
        ["run_id", "snapshot_time", "toolgroup", "kpi_name"],
        as_index=False,
    )["value"].max()
    wide = combined.pivot(
        index=["run_id", "snapshot_time", "toolgroup"],
        columns="kpi_name",
        values="value",
    ).reset_index()
    return wide.rename(columns=TOOL_AGG_KPIS)


def _wide_tg_at_snapshot(
    csv_dir: Path,
    target: float,
    tolerance: float,
) -> pd.DataFrame:
    """TG-wide KPI + tool max merge at one snapshot without loading full CSV."""
    tg_path = csv_dir / "kpi_toolgroup.csv"
    raw = _rows_near_snapshot(
        tg_path,
        target,
        tolerance,
        usecols=["run_id", "snapshot_time", "scope", "kpi_name", "value", "window_minutes"],
    )
    if raw.empty:
        return pd.DataFrame()
    snaps = raw["snapshot_time"].astype(float).unique()
    snap_use = float(min(snaps, key=lambda t: abs(t - target)))
    raw = raw[raw["snapshot_time"].astype(float) == snap_use].copy()
    raw["snapshot_time"] = snap_use

    tmp = csv_dir / ".ml_infer_tg_tmp.csv"
    raw.to_csv(tmp, index=False)
    try:
        wide = pivot_toolgroup_long(tmp)
    finally:
        tmp.unlink(missing_ok=True)

    tool_path = csv_dir / "kpi_tool.csv"
    if tool_path.is_file():
        tool_agg = _aggregate_tool_near_snapshot(tool_path, snap_use, tolerance)
        if not tool_agg.empty:
            wide = wide.merge(
                tool_agg,
                on=["run_id", "snapshot_time", "toolgroup"],
                how="left",
            )
            for col in TOOL_AGG_KPIS.values():
                if col in wide.columns:
                    wide[col] = wide[col].fillna(0.0)
    return wide


def build_inference_features_at_t0(
    csv_dir: Path,
    *,
    t0: float,
    tolerance: float,
) -> pd.DataFrame:
    """Cold-start KPI at T0 (+ delta from T0-120); chunked read near T0 only."""
    wide_t0 = _wide_tg_at_snapshot(csv_dir, t0, tolerance)
    if wide_t0.empty:
        raise ValueError(
            f"No KPI rows within tolerance={tolerance} of t0={t0} in {csv_dir}. "
            "Use cold-start sim_csv_out from run_sim_csv_once."
        )
    snap = float(wide_t0["snapshot_time"].iloc[0])
    if abs(snap - t0) > tolerance:
        raise ValueError(f"Resolved snapshot {snap} outside tolerance of t0={t0}")

    wide_past = _wide_tg_at_snapshot(csv_dir, t0 - DELTA_LAG_MIN, tolerance)
    out = wide_t0.copy()
    if "toolgroup" not in out.columns and "scope" in out.columns:
        out = out.rename(columns={"scope": "toolgroup"})

    past_map: dict[str, pd.Series] = {}
    if not wide_past.empty:
        wp = wide_past.copy()
        if "toolgroup" not in wp.columns and "scope" in wp.columns:
            wp = wp.rename(columns={"scope": "toolgroup"})
        past_map = {c: wp.set_index("toolgroup")[c] for c in DELTA_KPI_COLS if c in wp.columns}

    for c in DELTA_KPI_COLS:
        lag = past_map.get(c)
        if c in out.columns and lag is not None:
            out[f"{c}{DELTA_SUFFIX}"] = out[c].fillna(0) - out["toolgroup"].map(lag).fillna(0)
        else:
            out[f"{c}{DELTA_SUFFIX}"] = 0.0

    print(
        f"Inference KPI snapshot @ T0: {snap} "
        f"(requested t0={t0}, predict horizon t0+{LOOKAHEAD_MIN:.0f})"
    )
    print(f"  feature rows at T0: {len(out):,}")
    return out


def _scale_features(df: pd.DataFrame, train_mask: np.ndarray) -> pd.DataFrame:
    out = df.copy()
    for tg, g in out.groupby("toolgroup"):
        idx = g.index
        tr = train_mask[idx]
        for col in FEATURE_COLS:
            if col not in out.columns:
                out.loc[idx, col] = 0.0
                continue
            vmin = out.loc[idx[tr], col].min()
            vmax = out.loc[idx[tr], col].max()
            if vmax > vmin:
                out.loc[idx, col] = (out.loc[idx, col] - vmin) / (vmax - vmin)
            else:
                out.loc[idx, col] = 0.0
    return out


def _snapshot_at_t0(df: pd.DataFrame, t0: float, tolerance: float) -> float:
    """Resolve KPI snapshot at sim T0 (cold-start CSV). No nearest fallback beyond tolerance."""
    times = np.sort(df["snapshot_time"].astype(float).unique())
    if len(times) == 0:
        raise ValueError("No snapshot_time rows for inference")
    within = [float(t) for t in times if abs(t - t0) <= tolerance]
    if within:
        for t in within:
            if abs(t - t0) < 1e-6:
                return t
        return min(within, key=lambda t: abs(t - t0))
    nearest = float(times[np.argmin(np.abs(times - t0))])
    raise ValueError(
        f"No KPI snapshot within tolerance={tolerance} of t0={t0}. "
        f"Nearest available: {nearest}. "
        "Use cold-start sim_csv_out from run_sim_csv_once (not FORWARD run output)."
    )


def train_model(wide: pd.DataFrame, *, random_state: int):
    from sklearn.metrics import roc_auc_score
    from xgboost import XGBClassifier

    missing = [c for c in FEATURE_COLS if c not in wide.columns]
    if missing:
        raise KeyError(f"Missing feature columns: {missing}")

    train_mask = _temporal_train_mask(wide, train_frac=0.70)
    scaled = _scale_features(wide, train_mask)

    train_df = scaled[train_mask]
    test_df = scaled[~train_mask]
    X_train = train_df[FEATURE_COLS]
    y_train = train_df["y_bottleneck"]
    X_test = test_df[FEATURE_COLS]
    y_test = test_df["y_bottleneck"]

    model = XGBClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=random_state,
        eval_metric="logloss",
    )
    print(f"Train rows: {len(X_train):,}  Test rows: {len(X_test):,}")
    model.fit(X_train, y_train)
    proba_test = model.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test, proba_test) if y_test.nunique() > 1 else float("nan")
    print(f"Test ROC-AUC (proxy): {auc:.4f}")
    return model, scaled


def infer_at_t0(
    model,
    scaled_history: pd.DataFrame,
    inference_csv_dir: Path,
    *,
    t0: float,
    tolerance: float,
) -> pd.DataFrame:
    """Build feature rows at T0 snapshot from cold-start CSV + scaler from history."""
    rows_at = build_inference_features_at_t0(
        inference_csv_dir,
        t0=t0,
        tolerance=tolerance,
    )
    snap = float(rows_at["snapshot_time"].iloc[0])
    bn_by_tg = bn_t0_rule_from_rows(rows_at)

    train_mask = _temporal_train_mask(scaled_history, train_frac=0.70)
    scaler_ref = _scale_features(scaled_history, train_mask)
    scaled_rows = rows_at.copy()

    for tg in scaled_rows["toolgroup"].unique():
        ref = scaler_ref[scaler_ref["toolgroup"] == tg]
        if ref.empty:
            continue
        idx = scaled_rows["toolgroup"] == tg
        for col in FEATURE_COLS:
            if col not in ref.columns:
                continue
            vmin, vmax = ref[col].min(), ref[col].max()
            raw = rows_at.loc[idx, col]
            if vmax > vmin:
                scaled_rows.loc[idx, col] = (raw - vmin) / (vmax - vmin)
            else:
                scaled_rows.loc[idx, col] = 0.0

    X = scaled_rows[FEATURE_COLS]
    proba = model.predict_proba(X)[:, 1]
    scaled_rows["proba"] = proba
    scaled_rows["snapshot_time_infer"] = snap
    scaled_rows["bn_t0_rule"] = scaled_rows["toolgroup"].map(
        lambda g: int(bn_by_tg.get(str(g), False))
    )
    return scaled_rows


def bn_t0_rule_from_rows(rows: pd.DataFrame) -> dict[str, bool]:
    """bn@T0 from feature rows already loaded at T0 (no full CSV re-read)."""
    th = BottleneckThresholds()
    out: dict[str, bool] = {}
    for _, row in rows.iterrows():
        tg = str(row.get("toolgroup", "")).strip()
        if tg:
            out[tg] = bottleneck_flag(row, thresholds=th)
    return out


def export_shap(
    model,
    X_alarm: pd.DataFrame,
    meta: pd.DataFrame,
    *,
    top_k: int,
    out_path: Path,
) -> None:
    try:
        import shap
    except ImportError:
        print("shap not installed; skip SHAP export", file=sys.stderr)
        return

    explainer = shap.TreeExplainer(model, feature_perturbation="interventional")
    sv = explainer.shap_values(X_alarm)
    if isinstance(sv, list):
        sv = sv[1]
    rows = []
    for i in range(len(X_alarm)):
        contrib = sorted(
            zip(FEATURE_COLS, sv[i], X_alarm.iloc[i].values),
            key=lambda x: abs(x[1]),
            reverse=True,
        )[:top_k]
        for feat, shap_v, val in contrib:
            rows.append({
                "toolgroup": meta.iloc[i]["toolgroup"],
                "proba": meta.iloc[i]["proba"],
                "feature": feat,
                "shap": float(shap_v),
                "value": float(val),
            })
    pd.DataFrame(rows).to_csv(out_path, index=False)
    print(f"Wrote SHAP top features: {out_path}")


def main() -> int:
    p = argparse.ArgumentParser(description="ML G* @ T0 + audit (train/infer)")
    p.add_argument("--train-csv-dir", type=Path, default=_ROOT / "sim_csv_out")
    p.add_argument(
        "--inference-csv-dir",
        type=Path,
        default=_ROOT / "sim_csv_out",
        help="Cold-start KPI CSV (run_sim_csv_once); must include snapshot at --t0",
    )
    p.add_argument("--t0", type=float, default=26820.0)
    p.add_argument("--horizon", type=float, default=120.0)
    p.add_argument("--tolerance", type=float, default=1.0)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--alarm-threshold", type=float, default=0.7)
    p.add_argument("--snapshot-stride", type=int, default=10, help="Train subsample (10=every 10th snap)")
    p.add_argument("--skip-tool-agg", action="store_true", help="Faster train; less accurate")
    p.add_argument("--model-path", type=Path, default=None, help="Skip train if set")
    p.add_argument("--infer-only", action="store_true")
    p.add_argument("--shap-top-k", type=int, default=5)
    p.add_argument("--anchor-tg", default="", help="Default: highest proba in G*")
    p.add_argument("--chunksize", type=int, default=2_000_000)
    args = p.parse_args()

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = args.model_path or (out_dir / "ml_model.joblib")

    if args.infer_only and model_path.is_file():
        import joblib
        payload = joblib.load(model_path)
        model = payload["model"]
        scaled_history = payload["scaled_history"]
        print(f"Loaded model: {model_path}")
    else:
        wide = build_labeled_wide(
            args.train_csv_dir,
            horizon=args.horizon,
            snapshot_stride=args.snapshot_stride,
            skip_tool_agg=args.skip_tool_agg,
            chunksize=args.chunksize,
        )
        model, scaled_history = train_model(wide, random_state=42)
        import joblib
        joblib.dump({"model": model, "scaled_history": scaled_history}, model_path)
        print(f"Saved model: {model_path}")

    pred = infer_at_t0(
        model,
        scaled_history,
        args.inference_csv_dir,
        t0=args.t0,
        tolerance=args.tolerance,
    )
    snap = float(pred["snapshot_time_infer"].iloc[0])

    thr = float(args.alarm_threshold)
    pred["y_pred_alarm"] = (pred["proba"] >= thr).astype(int)
    pred["in_g_star"] = pred["y_pred_alarm"]
    pred["eligible_B"] = (pred["in_g_star"] == 0).astype(int)

    g_star = sorted(pred.loc[pred["in_g_star"] == 1, "toolgroup"].astype(str).tolist())
    if not g_star:
        print("WARNING: G* is empty — lower --alarm-threshold or check inference CSV", file=sys.stderr)

    anchor = args.anchor_tg.strip()
    if not anchor and g_star:
        top = pred[pred["toolgroup"].isin(g_star)].sort_values("proba", ascending=False).iloc[0]
        anchor = str(top["toolgroup"])

    audit_cols = [
        "toolgroup", "proba", "y_pred_alarm", "in_g_star",
        "bn_t0_rule", "eligible_B", "snapshot_time_infer",
    ]
    audit_path = out_dir / f"ml_alarm_audit_t{int(args.t0)}.csv"
    pred[audit_cols].sort_values(["in_g_star", "proba"], ascending=[False, False]).to_csv(
        audit_path, index=False,
    )

    g_path = out_dir / f"g_star_T{int(args.t0)}.json"
    g_payload = {
        "t0_sim_minute": args.t0,
        "inference_snapshot_time": snap,
        "alarm_threshold": thr,
        "anchor_tg": anchor,
        "toolgroups": g_star,
        "n_g_star": len(g_star),
        "n_eligible_B": int(pred["eligible_B"].sum()),
    }
    g_path.write_text(json.dumps(g_payload, indent=2) + "\n", encoding="utf-8")

    print(f"G* ({len(g_star)} TG): {g_star[:15]}{'...' if len(g_star) > 15 else ''}")
    print(f"Anchor: {anchor}")
    print(f"G* analysis pool: {len(g_star)} TG (g_star_analysis pipeline)")
    print(f"Eligible B (not in G*, ML audit only): {int(pred['eligible_B'].sum())} TG")
    print(f"Wrote {g_path}")
    print(f"Wrote {audit_path}")

    alarm_rows = pred[pred["y_pred_alarm"] == 1].head(30)
    if len(alarm_rows) > 0 and args.shap_top_k > 0:
        X_al = alarm_rows[FEATURE_COLS]
        export_shap(
            model,
            X_al,
            alarm_rows,
            top_k=args.shap_top_k,
            out_path=out_dir / f"ml_shap_top_t{int(args.t0)}.csv",
        )

    summary_path = out_dir / "ml_g_star_summary.txt"
    summary_path.write_text(
        "\n".join([
            f"t0={args.t0} inference_snap={snap}",
            f"alarm_threshold={thr}",
            f"g_star_n={len(g_star)}",
            f"eligible_B_n={int(pred['eligible_B'].sum())}",
            f"anchor={anchor}",
            "",
            "G* toolgroups:",
            *[f"  - {g}" for g in g_star],
        ]) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
