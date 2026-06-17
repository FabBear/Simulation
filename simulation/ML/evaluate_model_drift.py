"""③ 모델 드리프트 평가 → 임계 미달 시 Jenkins 재학습 잡 트리거.

tt_ml_bottleneck_pred에 쌓인 (예측 is_bottleneck_pred vs 정답 is_bottleneck_true)를
평가 윈도우로 조회해 F1을 계산하고, DRIFT_THRESHOLD 미만이면 재학습 파이프라인을 호출한다.

가드:
- 표본 부족(콜드스타트): MIN_SAMPLES 미만이면 평가 스킵.
- 무한루프 방지: 트리거 후 COOLDOWN_SEC 동안 재트리거 생략(마커 파일).
- Jenkins CSRF: crumbIssuer로 crumb 받아 POST 헤더에 첨부.
- 안전 테스트: DRIFT_DRY_RUN=1 이면 실제 빌드 POST 대신 로그만.

실행:  .venv/bin/python ML/evaluate_model_drift.py
"""

import os
import time
from pathlib import Path

import pandas as pd
import requests
from sklearn.metrics import precision_recall_fscore_support
from sqlalchemy import create_engine, text

# ── 설정 (환경변수 override) ───────────────────────────────
DRIFT_THRESHOLD = float(os.environ.get("DRIFT_THRESHOLD", "0.70"))
MIN_SAMPLES = int(os.environ.get("DRIFT_MIN_SAMPLES", "50"))
EVAL_WINDOW_HOURS = int(os.environ.get("DRIFT_EVAL_WINDOW_HOURS", "24"))
COOLDOWN_SEC = int(os.environ.get("RETRAIN_COOLDOWN_SEC", "3600"))
DRY_RUN = os.environ.get("DRIFT_DRY_RUN", "0") == "1"

# Jenkins (보안: 환경변수)
JENKINS_URL = os.environ.get("JENKINS_URL", "http://localhost:8081")
JENKINS_JOB = "FabGuard-ML-Retrain-Pipeline"
JENKINS_USER = os.environ.get("JENKINS_USER", "admin")
JENKINS_TOKEN = os.environ.get("JENKINS_TOKEN", "")

_MARKER = Path(__file__).resolve().parent / ".last_retrain_trigger"


def _engine():
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    user = os.environ.get("POSTGRES_USER", "fabbear_user")
    pw = os.environ.get("POSTGRES_PASSWORD", "fabbear_pw")
    db = os.environ.get("POSTGRES_DB", "fabbear")
    return create_engine(f"postgresql://{user}:{pw}@{host}:{port}/{db}")


def fetch_labeled_eval_data():
    """라벨된 (정답, 예측) 쌍을 평가 윈도우(created_at 최근 N시간)로 조회."""
    print(f"Fetching labeled predictions (last {EVAL_WINDOW_HOURS}h)...")
    sql = text(
        "SELECT is_bottleneck_true::int AS y_true, is_bottleneck_pred::int AS y_pred "
        "FROM public.tt_ml_bottleneck_pred "
        "WHERE is_bottleneck_true IS NOT NULL "
        "  AND created_at >= NOW() - make_interval(hours => :hours)"
    )
    with _engine().connect() as conn:
        df = pd.read_sql(sql, conn, params={"hours": EVAL_WINDOW_HOURS})
    return df["y_true"].to_numpy(), df["y_pred"].to_numpy()


def _in_cooldown() -> bool:
    if not _MARKER.exists():
        return False
    return (time.time() - _MARKER.stat().st_mtime) < COOLDOWN_SEC


def trigger_jenkins_retrain():
    """Jenkins REST API(+CSRF crumb)로 재학습 Job 트리거. 쿨다운/DRY_RUN 가드."""
    if _in_cooldown():
        print(f"⏸️ 쿨다운 중({COOLDOWN_SEC}s) — 재학습 트리거 생략")
        return
    if DRY_RUN:
        print(f"🧪 DRY_RUN: 실제 트리거 생략 (would POST {JENKINS_URL}/job/{JENKINS_JOB}/build)")
        return
    print(f"Triggering Jenkins Job: {JENKINS_JOB}...")
    try:
        s = requests.Session()
        s.auth = (JENKINS_USER, JENKINS_TOKEN)
        crumb = s.get(f"{JENKINS_URL}/crumbIssuer/api/json", timeout=10)
        if crumb.status_code == 200:
            j = crumb.json()
            s.headers[j["crumbRequestField"]] = j["crumb"]
            print("  CSRF crumb 획득")
        else:
            print(f"  ⚠️ crumb 조회 실패 HTTP {crumb.status_code} (CSRF 비활성일 수 있음)")
        resp = s.post(f"{JENKINS_URL}/job/{JENKINS_JOB}/build", timeout=10)
        if resp.status_code in (200, 201, 202):
            print(f"✅ 재학습 파이프라인 트리거 성공 (HTTP {resp.status_code})")
            _MARKER.write_text(str(time.time()))
        else:
            print(f"❌ 트리거 실패 HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"❌ Jenkins 트리거 오류: {e}")


def evaluate_drift():
    y_true, y_pred = fetch_labeled_eval_data()
    n = len(y_true)
    print(f"평가 표본(라벨됨): {n}건")

    if n < MIN_SAMPLES:
        print(f"⏸️ 표본 부족({n} < {MIN_SAMPLES}) — 드리프트 평가 스킵(콜드스타트 보호)")
        return

    p, r, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average="binary", zero_division=0
    )
    print(f"Drift Eval — Precision: {p:.4f}, Recall: {r:.4f}, F1: {f1:.4f} (threshold {DRIFT_THRESHOLD})")

    if p < DRIFT_THRESHOLD or f1 < DRIFT_THRESHOLD:
        print(f"🚨 MODEL DRIFT DETECTED! (threshold {DRIFT_THRESHOLD})")
        print("Initiating automated retraining pipeline...")
        trigger_jenkins_retrain()
    else:
        print("✅ Model performance is stable. No retraining required.")


if __name__ == "__main__":
    evaluate_drift()
