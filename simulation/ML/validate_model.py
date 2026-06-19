import os
import mlflow
from mlflow.tracking import MlflowClient
import sys

MODEL_NAME = "FabBear_Bottleneck_Model"
MIN_F1_SCORE = 0.70

def validate_and_promote():
    print("Starting Model Validation...")
    # [MLOps] 공유 MLflow Tracking 서버로 연결 (미설정 시 로컬 5500 기본값)
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5500"))
    client = MlflowClient()
    
    # 1. 모델 레지스트리에서 가장 최근에 등록된 버전 찾기
    versions = client.search_model_versions(f"name='{MODEL_NAME}'")
    if not versions:
        raise Exception(f"No versions found for model '{MODEL_NAME}'.")
        
    latest_version = max(versions, key=lambda v: int(v.version))
    version_num = latest_version.version
    run_id = latest_version.run_id
    
    print(f"Found latest model: Version {version_num} (Run ID: {run_id})")
    
    # 2. 해당 Run의 학습 메트릭(F1-Score) 가져오기
    run = client.get_run(run_id)
    val_best_f1 = run.data.metrics.get("val_best_f1", 0.0)
    
    print(f"Evaluation Metric (val_best_f1): {val_best_f1:.4f} (Threshold: {MIN_F1_SCORE})")
    
    # 3. 성능 검증 및 승격(Promotion)
    if val_best_f1 >= MIN_F1_SCORE:
        print("✅ Validation passed! Promoting model to 'Production' stage.")
        client.transition_model_version_stage(
            name=MODEL_NAME,
            version=version_num,
            stage="Production",
            archive_existing_versions=True
        )
    else:
        raise Exception(f"🚨 Validation failed! F1-Score {val_best_f1:.4f} is below the threshold {MIN_F1_SCORE}.")

if __name__ == "__main__":
    validate_and_promote()