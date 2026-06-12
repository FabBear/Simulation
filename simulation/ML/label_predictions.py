"""① 라벨링 배치: tt_ml_bottleneck_pred의 미라벨 예측에 T0+120 정답을 채운다.

각 예측(tg_name, snapshot_time)에 대해 snapshot_time+120 시점의 실제 KPI를
시뮬 KPI 소스(simulation.kpi_toolgroup/kpi_tool)에서 가져와, 학습과 동일한
공유 룰(label_rule.apply_label_rule)로 is_bottleneck_true를 산출해 UPDATE 한다.

- 멱등성: is_bottleneck_true IS NULL 행만 대상 (이미 라벨된 행은 건너뜀).
- 적재 방식 A(기본): MLOps 배치가 public.tt_ml_bottleneck_pred를 직접 UPDATE.
  (라벨링은 SSE 불필요·백엔드 무관. 대안 B: 백엔드 PATCH /api/internal/ml-predictions/labels 위임)
- ⚠️ KPI 소스: 현재 적재 데이터(run_id=live_inference_run, snapshot=시뮬 분)는 시뮬 소스 기반.
  라이브(ps_tg_metrics, epoch분) 전환 시 조회 대상만 교체하면 됨(LABEL_KPI_SOURCE 분기 지점 주석).

실행:  cd simulation && .venv/bin/python ML/label_predictions.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

_ML_DIR = Path(__file__).resolve().parent
_ROOT = _ML_DIR.parent
for _p in (str(_ML_DIR), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from database import engine  # noqa: E402
from label_rule import LABEL_KPI_COLS, THRESHOLD_KEYS, apply_label_rule  # noqa: E402
from data_preprocessing import compute_report_thresholds, load_and_merge_data  # noqa: E402

LOOKAHEAD_MIN = 120.0
PROCESSED_DIR = _ML_DIR / "processed_data"
PRED_TABLE = "public.tt_ml_bottleneck_pred"


def load_thresholds(ref_wide: pd.DataFrame | None = None) -> pd.Series:
    """학습 시 영속화한 분위수 cutoff 로드. 없으면 소스 분포에서 재계산(폴백).

    학습과 동일 run에서 재계산하면 동일값이지만, 원칙적으로는 학습 아티팩트를 쓴다.
    """
    path = PROCESSED_DIR / "label_thresholds.csv"
    if path.exists():
        thr = pd.read_csv(path, index_col=0)["value"]
        if set(THRESHOLD_KEYS).issubset(set(thr.index)):
            print(f"Loaded label thresholds from {path}")
            return thr
        print(f"⚠️ {path} 형식 불일치 → 재계산 폴백")
    if ref_wide is not None:
        print("⚠️ label_thresholds.csv 없음 → 소스 분포에서 재계산(학습과 동일 run이면 동일값)")
        return compute_report_thresholds(ref_wide)
    raise FileNotFoundError("label_thresholds.csv 없음 & 폴백용 ref_wide 미제공")


def latest_sim_run_id() -> str:
    with engine.connect() as conn:
        rid = conn.execute(
            text("SELECT run_id FROM simulation.kpi_toolgroup ORDER BY snapshot_time DESC LIMIT 1")
        ).scalar()
    if not rid:
        raise RuntimeError("simulation.kpi_toolgroup 데이터가 없습니다.")
    return rid


def label_predictions() -> None:
    # 1. 미라벨 예측 로드
    with engine.connect() as conn:
        preds = pd.read_sql(
            text(
                f"SELECT pred_id, tg_name, snapshot_time FROM {PRED_TABLE} "
                "WHERE is_bottleneck_true IS NULL"
            ),
            conn,
        )
    if preds.empty:
        print("미라벨 예측 없음. 종료.")
        return
    print(f"미라벨 예측: {len(preds)}건")

    # 2. 시뮬 KPI 소스에서 wide 테이블 구성 (미래 시점 조회용)
    #    [LABEL_KPI_SOURCE 분기 지점] 라이브 전환 시 여기서 ps_tg_metrics 기반 wide로 교체.
    run_id = latest_sim_run_id()
    wide = load_and_merge_data(run_id)  # columns: snapshot_time, toolgroup, *LABEL_KPI_COLS
    wide["snapshot_time"] = wide["snapshot_time"].astype(float)
    thr = load_thresholds(ref_wide=wide)

    # 3. 각 예측의 target_time(=snapshot_time+120)에 해당하는 미래 KPI 조인
    preds["target_time"] = preds["snapshot_time"].astype(float) + LOOKAHEAD_MIN
    merged = preds.merge(
        wide,
        left_on=["target_time", "tg_name"],
        right_on=["snapshot_time", "toolgroup"],
        how="left",
        suffixes=("", "_future"),
    )
    has_future = merged[LABEL_KPI_COLS[0]].notna()
    labelable = merged[has_future].copy()
    skipped = int((~has_future).sum())
    print(f"라벨링 가능: {len(labelable)}건 / 미래 KPI 미도달 스킵: {skipped}건")
    if labelable.empty:
        print("라벨링 가능 행 없음(미래 시점 미도달). 종료.")
        return

    # 4. 라벨 산출 — 학습과 동일한 공유 룰
    labelable["label"] = apply_label_rule(labelable, thr)

    # 5. UPDATE (배치, 트랜잭션)
    params = [
        {"pid": int(pid), "y": bool(y)}
        for pid, y in zip(labelable["pred_id"], labelable["label"])
    ]
    with engine.begin() as conn:
        conn.execute(
            text(
                f"UPDATE {PRED_TABLE} SET is_bottleneck_true = :y, updated_at = NOW() "
                "WHERE pred_id = :pid"
            ),
            params,
        )
    pos = int(labelable["label"].sum())
    print(
        f"✅ 라벨 UPDATE 완료: {len(params)}건 "
        f"(병목=1: {pos}, 정상=0: {len(params) - pos})"
    )


if __name__ == "__main__":
    label_predictions()
