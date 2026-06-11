import pandas as pd
import numpy as np
import mlflow
import shap
import json
import os
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
CSV_DIR = _ROOT / "sim_csv_out"
OUT_DIR = _ROOT / "out" / "ml_g_star_e2e"

# MLflow Model Registry URI 설정
MODEL_NAME = "FabGuard_Bottleneck_Model"
MODEL_STAGE = "Production"
MODEL_URI = f"models:/{MODEL_NAME}/{MODEL_STAGE}"
ALARM_PROBA_THRESHOLD = 0.7  # 병목 알람 임계값

def load_t0_data(t0_minute: float) -> pd.DataFrame:
    """
    TODO: 향후 PostgreSQL DB 조회로 변경 예정
    현재는 E2E 테스트를 위해 CSV에서 T0 시점 데이터를 읽어옵니다.
    """
    print(f"Loading T0={t0_minute} data from CSV...")
    # 실제 환경에서는 data_preprocessing.py의 로직을 활용해 T0 데이터를 생성합니다.
    # 여기서는 시연을 위한 파이프라인 뼈대를 구성합니다.
    # df_t0 = query_db_for_t0(t0_minute)
    
    # 임시 mock 데이터프레임 (스케일링이 완료된 형태라고 가정)
    mock_features = ['available_tool_ratio', 'q_time_min', 'wait_ratio', 'wip', 'utilization_avg', 'max_util', 
                     'q_time_min_delta_120', 'wait_ratio_delta_120', 'wip_delta_120', 'max_util_delta_120', 'utilization_avg_delta_120']
    
    df_t0 = pd.DataFrame({
        "snapshot_time": [t0_minute] * 5,
        "toolgroup": ["DefMEt_FE_118", "Dielectric_FE_30", "TF_Met_FE_61", "EPI_38", "DE_BE_66"]
    })
    for f in mock_features:
        df_t0[f] = np.random.rand(5)
        
    return df_t0

def run_inference(t0_minute: float):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    
    print(f"Loading model '{MODEL_NAME}' from stage '{MODEL_STAGE}'...")
    # MLflow에서 Production 모델 로드
    model = mlflow.xgboost.load_model(MODEL_URI)
    
    # T0 데이터 준비
    df_t0 = load_t0_data(t0_minute)
    feature_cols = [c for c in df_t0.columns if c not in ["snapshot_time", "toolgroup"]]
    X_t0 = df_t0[feature_cols]
    
    print("Predicting probabilities...")
    proba = model.predict_proba(X_t0)[:, 1]
    df_t0["proba"] = proba
    
    # G* (임계값 이상인 위험 ToolGroup) 필터링
    g_star_df = df_t0[df_t0["proba"] >= ALARM_PROBA_THRESHOLD].copy()
    
    if g_star_df.empty:
        print("No bottleneck predicted. Exiting.")
        return
        
    print(f"Detected {len(g_star_df)} bottleneck toolgroups. Running SHAP...")
    X_explain = g_star_df[feature_cols]
    
    # SHAP TreeExplainer
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_explain)
    
    # Handoff JSON 조립
    handoff_data = {
        "pipeline": "g_star_analysis",
        "target_agent": "root_cause",
        "analysis_rule": "ttest_g_star_analysis",
        "fdr_scope": "g_star_x_kpi",
        "fdr_n_hypotheses": len(g_star_df) * 5,
        "g_star_toolgroups": g_star_df["toolgroup"].tolist(),
        "evidence_data": [] # Track A 로직에서 추출한 g_star_kpi_evidence.csv 내용이 들어갈 자리
    }
    
    # G* 예측 결과 및 SHAP 데이터 저장
    g_star_out_path = OUT_DIR / f"g_star_T{int(t0_minute)}.json"
    
    # 여기서 g_star_kpi_evidence.csv 생성을 위한 Track A(Ljung-Box, t-test, FDR) 로직을 
    # 트리거하거나, 시뮬레이션 파이프라인에서 처리할 수 있도록 JSON을 넘겨줍니다.
    handoff_path = OUT_DIR / "agent_handoff_g_star_analysis.json"
    
    with open(g_star_out_path, "w", encoding="utf-8") as f:
        json.dump({
            "t0": t0_minute, 
            "alarm_threshold": ALARM_PROBA_THRESHOLD,
            "g_star": g_star_df[["toolgroup", "proba"]].to_dict(orient="records")
        }, f, indent=2)
        
    with open(handoff_path, "w", encoding="utf-8") as f:
        json.dump(handoff_data, f, indent=2, ensure_ascii=False)
        
    print(f"G* Handoff JSON generated at: {handoff_path}")

if __name__ == "__main__":
    run_inference(t0_minute=26820.0)