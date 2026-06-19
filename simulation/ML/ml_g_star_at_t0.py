import pandas as pd
import numpy as np
import mlflow
import json
import os
import requests
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
ML_DIR = Path(__file__).resolve().parent
PROCESSED_DIR = ML_DIR / "processed_data"
OUT_DIR = _ROOT / "out" / "ml_g_star_e2e"

# MLflow Model Registry URI 설정
MODEL_NAME = "FabBear_Bottleneck_Model"
MODEL_STAGE = "Production"
MODEL_URI = f"models:/{MODEL_NAME}/{MODEL_STAGE}"
ALARM_PROBA_THRESHOLD = 0.7  # 병목 알람 임계값

# 백엔드 API 주소 (로컬 테스트용 8080 포트)
BACKEND_API_URL = "http://localhost:8080/api/internal/ml-predictions"

def load_t0_data() -> pd.DataFrame:
    """
    실제 시뮬레이션 전처리 파이프라인이 생성한 X_test.parquet에서 
    가장 최근 시점(T0)의 데이터를 로드합니다.
    """
    print(f"Loading actual simulation data from {PROCESSED_DIR}...")
    df = pd.read_parquet(PROCESSED_DIR / "X_test.parquet")
    
    # 가장 마지막 시점을 T0로 설정
    t0_minute = df["snapshot_time"].max()
    print(f"Target T0 = {t0_minute}")
    
    df_t0 = df[df["snapshot_time"] == t0_minute].copy()
    return df_t0, t0_minute

def run_inference():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # [MLOps] 공유 MLflow Tracking 서버로 연결 (미설정 시 로컬 5500 기본값)
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5500"))
    print(f"Loading model '{MODEL_NAME}' from stage '{MODEL_STAGE}'...")
    model = mlflow.xgboost.load_model(MODEL_URI)
    
    # T0 데이터 준비
    df_t0, t0_minute = load_t0_data()
    feature_cols = [c for c in df_t0.columns if c not in ["snapshot_time", "toolgroup"]]
    X_t0 = df_t0[feature_cols]
    
    print("Predicting probabilities...")
    proba = model.predict_proba(X_t0)[:, 1]
    df_t0["proba"] = proba
    
    # --- [MLOps] 백엔드 API 연동 적재 ---
    print(f"Sending {len(df_t0)} predictions to Backend API ({BACKEND_API_URL})...")
    predictions_payload = []
    
    for _, row in df_t0.iterrows():
        pred_prob = float(row["proba"])
        predictions_payload.append({
            "runId": os.environ.get("SIM_SCENARIO_ID", "live_inference_run"),
            "snapshotTime": float(t0_minute),
            "tgName": str(row["toolgroup"]),
            "predProb": round(pred_prob, 4),
            "isBottleneckPred": bool(pred_prob >= ALARM_PROBA_THRESHOLD)
        })
        
    # 백엔드 내부 통신용 보안 토큰 (환경변수가 없으면 기본값 사용)
    internal_token = os.environ.get("INTERNAL_API_TOKEN", "your_internal_api_token")
    headers = {
        "X-Internal-Token": internal_token,
        "X-Event-Timestamp": datetime.now(timezone.utc).isoformat(),
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(BACKEND_API_URL, json={"predictions": predictions_payload}, headers=headers)
        response.raise_for_status()
        print(f"✅ Successfully saved predictions! (HTTP Status: {response.status_code})")
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to save predictions to backend API: {e}")
        if getattr(e, 'response', None) is not None:
            print(f"💡 백엔드 상세 거절 사유: {e.response.text}")

    # G* (임계값 이상인 위험 ToolGroup) 필터링
    g_star_df = df_t0[df_t0["proba"] >= ALARM_PROBA_THRESHOLD].copy()
    
    if g_star_df.empty:
        print("No bottleneck predicted.")
        return
        
    print(f"Detected {len(g_star_df)} bottleneck toolgroups.")

if __name__ == "__main__":
    run_inference()