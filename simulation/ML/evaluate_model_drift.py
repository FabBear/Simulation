import pandas as pd
import numpy as np
import requests
from sklearn.metrics import precision_recall_fscore_support
import os

# 설정값
DRIFT_THRESHOLD = 0.70

# Jenkins 서버 정보 (보안을 위해 환경변수 사용 권장)
JENKINS_URL = os.environ.get("JENKINS_URL", "http://your-jenkins-server:8081")
JENKINS_JOB = "FabGuard-ML-Retrain-Pipeline"
JENKINS_USER = os.environ.get("JENKINS_USER", "admin")
JENKINS_TOKEN = os.environ.get("JENKINS_TOKEN", "your_api_token")

def fetch_daily_eval_data():
    """
    TODO: 향후 PostgreSQL DB 조회로 변경 예정
    어제 하루 동안(106개 ToolGroup * 24시간 = 2544 스냅샷)의 모델 '예측값'과 
    실제 120분 뒤 발생한 'Ground Truth' 데이터를 조인하여 가져옵니다.
    """
    print("Fetching last 24h predictions and ground truth labels...")
    # 실제 환경의 DB Query 로직 대체용 임시 Mock Data
    n_samples = 106 * 24
    y_true = np.random.randint(0, 2, n_samples)
    # 성능이 저하된(Drift) 상태라고 가정한 예측값 생성
    y_pred = np.random.choice([0, 1], size=n_samples, p=[0.6, 0.4])
    
    return y_true, y_pred

def trigger_jenkins_retrain():
    """Jenkins REST API를 호출하여 재학습 Job을 트리거합니다."""
    print(f"Triggering Jenkins Job: {JENKINS_JOB}...")
    trigger_url = f"{JENKINS_URL}/job/{JENKINS_JOB}/build"
    
    try:
        response = requests.post(trigger_url, auth=(JENKINS_USER, JENKINS_TOKEN))
        if response.status_code in [200, 201]:
            print("Jenkins retrain pipeline triggered successfully.")
        else:
            print(f"Failed to trigger Jenkins. Status Code: {response.status_code}")
    except Exception as e:
        print(f"Error triggering Jenkins: {e}")

def evaluate_drift():
    y_true, y_pred = fetch_daily_eval_data()
    
    # Class 1(병목 발생)에 대한 평가지표 계산
    p, r, f1, _ = precision_recall_fscore_support(y_true, y_pred, average="binary", zero_division=0)
    
    print(f"Daily Evaluation - Precision: {p:.4f}, Recall: {r:.4f}, F1-Score: {f1:.4f}")
    
    # 드리프트 감지 로직: Precision 또는 F1-Score가 0.7 미만인지 확인
    if p < DRIFT_THRESHOLD or f1 < DRIFT_THRESHOLD:
        print(f"🚨 MODEL DRIFT DETECTED! (Threshold: {DRIFT_THRESHOLD})")
        print("Initiating automated retraining pipeline...")
        trigger_jenkins_retrain()
    else:
        print("✅ Model performance is stable. No retraining required.")
        
if __name__ == "__main__":
    evaluate_drift()