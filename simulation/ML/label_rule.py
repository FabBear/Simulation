"""병목 정답 라벨 룰 (4가지) — 학습/라이브 라벨링 단일 진실원.

data_preprocessing.py(학습 라벨)와 label_predictions.py(라이브 정답 라벨)가
**반드시 동일한 룰+임계값**을 쓰도록 이 한 함수를 공유한다.

임계값(thr)은 학습 시 분포에서 계산한 분위수 cutoff를 그대로 사용한다:
  Q, Q_MAX, W, WIP, A, U_HI, U_LO  (data_preprocessing.REPORT_THRESHOLD_QUANTILES)

룰 (T+120 시점 KPI 기준, 하나라도 참이면 병목=1):
  1) 대기/큐 : q_time >= Q  AND (wait_ratio >= W  OR  wip >= WIP)
  2) 가용부족: available_tool_ratio <= A
  3) 가동불균형: max_util >= U_HI  AND  utilization_avg < U_LO
  4) 최대큐  : max_avg_q_time >= Q_MAX  AND  wait_ratio < W
"""

from __future__ import annotations

from typing import Mapping

import pandas as pd

# 룰 평가에 필요한 KPI 컬럼 (df에 이 이름들이 있어야 함; 미래 시점 값)
LABEL_KPI_COLS = [
    "q_time_min",
    "wait_ratio",
    "wip",
    "available_tool_ratio",
    "utilization_avg",
    "max_util",
    "max_avg_q_time",
]

THRESHOLD_KEYS = ["Q", "Q_MAX", "W", "WIP", "A", "U_HI", "U_LO"]


def apply_label_rule(df: pd.DataFrame, thr: Mapping[str, float]) -> pd.Series:
    """df(미래 시점 KPI 컬럼 보유) + thr(분위수 cutoff) → 병목 라벨(int8 Series)."""

    def col(name: str) -> pd.Series:
        if name in df.columns:
            return pd.to_numeric(df[name], errors="coerce").fillna(0.0)
        return pd.Series(0.0, index=df.index)

    q = col("q_time_min")
    w = col("wait_ratio")
    wip = col("wip")
    avail = col("available_tool_ratio")
    util = col("utilization_avg")
    max_util = col("max_util")
    max_q = col("max_avg_q_time")

    return (
        ((q >= thr["Q"]) & ((w >= thr["W"]) | (wip >= thr["WIP"])))
        | (avail <= thr["A"])
        | ((max_util >= thr["U_HI"]) & (util < thr["U_LO"]))
        | ((max_q >= thr["Q_MAX"]) & (w < thr["W"]))
    ).astype("int8")
