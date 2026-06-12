import pandas as pd
import numpy as np
import sys
from pathlib import Path
from typing import Literal, Tuple, List, Dict

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

# [MLOps] DB 연동을 위한 모듈 추가
from sqlalchemy import text
from database import engine

CSV_DIR = _ROOT / "sim_csv_out"
OUT_DIR = Path(__file__).resolve().parent / "processed_data"

# Constants & Settings
LOOKAHEAD_MIN = 120.0
DELTA_LAG_MIN = 120.0
TRAIN_FRAC, VAL_FRAC, TEST_FRAC = 0.70, 0.15, 0.15

TG_INSTANT = ("q_time_min", "wait_ratio", "wip", "available_tool_ratio")
TG_UTIL = ("utilization_avg", "setup_ratio_avg")
TOOL_KPIS = {"utilization": "max_util", "avg_q_time": "max_avg_q_time"}

REPORT_THRESHOLD_QUANTILES: Dict[str, Tuple[str, Literal["upper", "lower"], float]] = {
    "Q": ("q_time_min", "upper", 0.97),
    "Q_MAX": ("max_avg_q_time", "upper", 0.97),
    "W": ("wait_ratio", "upper", 0.97),
    "WIP": ("wip", "upper", 0.97),
    "A": ("available_tool_ratio", "lower", 0.01),
    "U_HI": ("max_util", "upper", 0.75),
    "U_LO": ("utilization_avg", "lower", 0.95),
}

LABEL_KPI_COLS = [
    "q_time_min", "wait_ratio", "wip", "available_tool_ratio",
    "utilization_avg", "max_util", "max_avg_q_time",
]

DELTA_KPI_COLS = ["q_time_min", "wait_ratio", "wip", "max_util", "utilization_avg"]
TG_MINMAX_SCALE_COLS = list(dict.fromkeys([*LABEL_KPI_COLS, "setup_ratio_avg"] + [f"{c}_delta_120" for c in DELTA_KPI_COLS]))

def load_and_merge_data(run_id: str) -> pd.DataFrame:
    """PostgreSQL DB에서 특정 run_id의 TG 및 Tool 단위 KPI 데이터를 로드하고 wide 형식으로 병합합니다."""
    print(f"Loading TG data from DB for run_id='{run_id}'...")
    
    # [MLOps] public.kpi_toolgroup 테이블에서 필요한 데이터만 Raw SQL로 조회 (메모리 최적화)
    tg_query = text("""
        SELECT snapshot_time, scope AS toolgroup, kpi_name, value, window_minutes
        FROM public.kpi_toolgroup
        WHERE run_id = :run_id
    """)
    tg_long = pd.read_sql(tg_query, engine, params={"run_id": run_id})
    tg_long["snapshot_time"] = tg_long["snapshot_time"].astype(float)

    instant = tg_long[tg_long["window_minutes"].isna() | (tg_long["window_minutes"] == "")]
    instant = instant[instant["kpi_name"].isin(TG_INSTANT)]
    tg_wide = instant.pivot_table(index=["snapshot_time", "toolgroup"], columns="kpi_name", values="value", aggfunc="first").reset_index()

    util = tg_long[tg_long["kpi_name"].isin(TG_UTIL)]
    tg_wide_util = util.pivot_table(index=["snapshot_time", "toolgroup"], columns="kpi_name", values="value", aggfunc="first").reset_index()
    tg_wide = tg_wide.merge(tg_wide_util, on=["snapshot_time", "toolgroup"], how="outer")

    print(f"Loading Tool data from DB for run_id='{run_id}'...")
    def tool_id_to_toolgroup(tool_id: str) -> str:
        return tool_id.rsplit("#", 1)[0] if "#" in tool_id else tool_id

    # [MLOps] 대용량 kpi_tool 테이블은 WHERE 조건으로 필터링하여 DB단에서 데이터 량을 줄여서 쿼리
    # 덕분에 청크(chunk) 처리가 불필요해지고 OOM 방지 및 성능이 크게 향상됨
    tool_query = text("""
        SELECT snapshot_time, scope, kpi_name, value
        FROM public.kpi_tool
        WHERE run_id = :run_id
          AND kpi_name IN ('utilization', 'avg_q_time')
    """)
    tool_long = pd.read_sql(tool_query, engine, params={"run_id": run_id})
    
    if not tool_long.empty:
        tool_long["toolgroup"] = tool_long["scope"].map(tool_id_to_toolgroup)
        tool_long["snapshot_time"] = tool_long["snapshot_time"].astype(float)
        tool_combined = tool_long.groupby(["snapshot_time", "toolgroup", "kpi_name"], as_index=False)["value"].max()
    else:
        tool_combined = pd.DataFrame(columns=["snapshot_time", "toolgroup", "kpi_name", "value"])
        
    tool_agg = tool_combined.pivot(index=["snapshot_time", "toolgroup"], columns="kpi_name", values="value").reset_index()
    tool_agg = tool_agg.rename(columns=TOOL_KPIS)

    wide = tg_wide.merge(tool_agg, on=["snapshot_time", "toolgroup"], how="left")
    wide["max_util"] = wide["max_util"].fillna(0.0)
    wide["max_avg_q_time"] = wide["max_avg_q_time"].fillna(0.0)
    return wide

def compute_report_thresholds(ref: pd.DataFrame) -> pd.Series:
    """학습 데이터 기반 분위수 임계값을 계산합니다."""
    out: Dict[str, float] = {}
    for param, (col, _, q) in REPORT_THRESHOLD_QUANTILES.items():
        s = pd.to_numeric(ref[col], errors="coerce").dropna()
        out[param] = float(s.quantile(q))
    return pd.Series(out)

def process_features_and_labels(df: pd.DataFrame, report_thr: pd.Series) -> pd.DataFrame:
    """T+120 라벨을 할당하고, T-120 델타 피처를 생성합니다."""
    # 1. T+120 Labeling
    keys = ["snapshot_time", "toolgroup"]
    future = df[[*keys, *LABEL_KPI_COLS]].copy()
    future = future.rename(columns={c: f"{c}_future" for c in LABEL_KPI_COLS})
    future["snapshot_time"] = future["snapshot_time"] - LOOKAHEAD_MIN
    df = df.merge(future, on=keys, how="inner")

    q, q_max = report_thr["Q"], report_thr["Q_MAX"]
    w, wip_thr = report_thr["W"], report_thr["WIP"]
    a, u_hi, u_lo = report_thr["A"], report_thr["U_HI"], report_thr["U_LO"]

    df["y_bottleneck"] = (
        ((df["q_time_min_future"].fillna(0) >= q) & ((df["wait_ratio_future"].fillna(0) >= w) | (df["wip_future"].fillna(0) >= wip_thr))) |
        (df["available_tool_ratio_future"].fillna(0) <= a) |
        ((df["max_util_future"].fillna(0) >= u_hi) & (df["utilization_avg_future"].fillna(0) < u_lo)) |
        ((df["max_avg_q_time_future"].fillna(0) >= q_max) & (df["wait_ratio_future"].fillna(0) < w))
    ).astype("int8")

    # 2. T-120 Delta Feature Engineering
    past = df[[*keys, *DELTA_KPI_COLS]].copy()
    past = past.rename(columns={c: f"{c}_lag120" for c in DELTA_KPI_COLS})
    past["snapshot_time"] = past["snapshot_time"] + DELTA_LAG_MIN
    df = df.merge(past, on=keys, how="inner")

    for c in DELTA_KPI_COLS:
        df[f"{c}_delta_120"] = pd.to_numeric(df[c], errors="coerce") - pd.to_numeric(df[f"{c}_lag120"], errors="coerce")
    return df

def temporal_split(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """시간축(snapshot_time) 기준으로 데이터를 Train/Val/Test 로 분할합니다."""
    times = np.sort(df["snapshot_time"].astype(float).unique())
    n_t = len(times)
    t_train_max = times[max(1, min(int(n_t * TRAIN_FRAC), n_t - 2)) - 1]
    t_val_max = times[max(1, min(int(n_t * (TRAIN_FRAC + VAL_FRAC)), n_t - 1)) - 1]

    train = df[df["snapshot_time"] <= t_train_max].copy()
    val = df[(df["snapshot_time"] > t_train_max) & (df["snapshot_time"] <= t_val_max)].copy()
    test = df[df["snapshot_time"] > t_val_max].copy()
    return train, val, test

def fit_and_transform_minmax(train: pd.DataFrame, val: pd.DataFrame, test: pd.DataFrame, stats_path: Path):
    """Train 기준으로 TG별 Min-Max 통계를 구하고 전체 데이터셋을 스케일링합니다."""
    rows = []
    for tg, g in train.groupby("toolgroup", sort=False):
        for c in TG_MINMAX_SCALE_COLS:
            if c in g.columns:
                s = pd.to_numeric(g[c], errors="coerce")
                rows.append({"toolgroup": tg, "feature": c, "vmin": float(s.min()) if s.notna().any() else 0.0, "vmax": float(s.max()) if s.notna().any() else 0.0})
    
    stats = pd.DataFrame(rows)
    stats.to_csv(stats_path, index=False)

    vmin_w = stats.pivot(index="toolgroup", columns="feature", values="vmin")
    vmax_w = stats.pivot(index="toolgroup", columns="feature", values="vmax")

    def transform(df):
        for c in TG_MINMAX_SCALE_COLS:
            if c in df.columns:
                vmin, vmax = df["toolgroup"].map(vmin_w[c]), df["toolgroup"].map(vmax_w[c])
                denom = (vmax - vmin).clip(lower=1e-9)
                constant = (vmax - vmin).abs() <= 1e-9
                df[c] = ((pd.to_numeric(df[c], errors="coerce") - vmin) / denom).where(~constant, 0.5).clip(0.0, 1.0)
        return df

    return transform(train), transform(val), transform(test)

def preprocess_data():
    """전체 데이터 전처리 파이프라인을 실행합니다."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # [MLOps] DB에서 가져올 특정 run_id 지정
    target_run_id = 'ece173272af7'
    df_wide = load_and_merge_data(target_run_id)
    report_thr = compute_report_thresholds(df_wide)
    df_processed = process_features_and_labels(df_wide, report_thr)
    
    train, val, test = temporal_split(df_processed)
    
    stats_path = OUT_DIR / "tg_minmax_stats.csv"
    train, val, test = fit_and_transform_minmax(train, val, test, stats_path)
    
    # 사용할 수치형 피처 필터링 (라벨, 식별자, lag, future 등 제외)
    exclude = {"snapshot_time", "run_id", "y_bottleneck", "max_avg_q_time", "setup_ratio_avg"}
    feature_cols = [c for c in train.columns if c not in exclude and c != "toolgroup" and "_future" not in c and "_lag" not in c and pd.api.types.is_numeric_dtype(train[c])]
    
    for name, df in zip(["train", "val", "test"], [train, val, test]):
        X = df[["snapshot_time", "toolgroup"] + feature_cols]
        y = df[["snapshot_time", "toolgroup", "y_bottleneck"]]
        X.to_parquet(OUT_DIR / f"X_{name}.parquet", index=False)
        y.to_parquet(OUT_DIR / f"y_{name}.parquet", index=False)
        print(f"Saved {name} datasets. Shape: X={X.shape}, y={y.shape}")

if __name__ == "__main__":
    preprocess_data()