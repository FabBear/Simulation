import pandas as pd
import numpy as np
import mlflow
import mlflow.xgboost
from xgboost import XGBClassifier
from sklearn.metrics import precision_recall_fscore_support
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
PROCESSED_DIR = _ROOT / "processed_data"

# Model Hyperparameters matches Jupyter Notebook PoC
MODEL_PARAMS = {
    "n_estimators": 300,
    "max_depth": 10,
    "learning_rate": 0.06,
    "min_child_weight": 2,
    "subsample": 0.85,
    "colsample_bytree": 0.85,
    "reg_lambda": 1.0,
    "objective": "binary:logistic",
    "eval_metric": "logloss",
    "random_state": 42,
    "n_jobs": -1
}

def run_training_pipeline():
    """MLflow 연동을 포함한 XGBoost 모델 학습 및 임계값 튜닝 파이프라인을 실행합니다."""
    print("Loading preprocessed data...")
    X_train = pd.read_parquet(PROCESSED_DIR / "X_train.parquet")
    y_train = pd.read_parquet(PROCESSED_DIR / "y_train.parquet")
    X_val = pd.read_parquet(PROCESSED_DIR / "X_val.parquet")
    y_val = pd.read_parquet(PROCESSED_DIR / "y_val.parquet")
    
    # 피처만 선택 (식별용 컬럼 제외)
    feature_cols = [c for c in X_train.columns if c not in ["snapshot_time", "toolgroup"]]
    
    _X_train = X_train[feature_cols].fillna(0.0)
    _X_val = X_val[feature_cols].fillna(0.0)
    _y_train = y_train["y_bottleneck"].astype(int).values
    _y_val = y_val["y_bottleneck"].astype(int).values
    
    # Imbalance treatment
    scale_pos_weight = float((_y_train == 0).sum() / max(1, (_y_train == 1).sum()))
    print(f"Calculated scale_pos_weight: {scale_pos_weight:.4f}")
    
    mlflow.set_experiment("FabGuard_Bottleneck_Prediction")
    with mlflow.start_run() as run:
        mlflow.xgboost.autolog()
        
        model = XGBClassifier(**MODEL_PARAMS, scale_pos_weight=scale_pos_weight)
        
        print("Training XGBoost Model...")
        model.fit(_X_train, _y_train, eval_set=[(_X_val, _y_val)], verbose=50)
        
        # Threshold Sweep
        print("Tuning Classification Threshold...")
        val_proba = model.predict_proba(_X_val)[:, 1]
        best_threshold, best_f1, best_precision = 0.5, 0.0, 0.0
        
        for t in np.arange(0.05, 0.96, 0.05):
            pred = (val_proba >= t).astype(int)
            p, r, f1, _ = precision_recall_fscore_support(_y_val, pred, average="binary", zero_division=0)
            if f1 > best_f1:
                best_f1 = f1
                best_precision = p
                best_threshold = t
                
        print(f"Optimal Threshold found: {best_threshold:.2f} (F1-score: {best_f1:.4f})")
        mlflow.log_metric("ALARM_PROBA_THRESHOLD", best_threshold)
        mlflow.log_metric("val_best_f1", best_f1)
        # [MLOps] 드리프트 감지 기준 지표(Precision) 로깅
        mlflow.log_metric("val_best_precision", best_precision)

        # [MLOps] 모델 버전 관리용 레지스트리 등록
        # 주의: 여기서는 모델을 등록만 하고, Production 승격은 validate_model.py에서 수행합니다.
        mlflow.register_model(model_uri=f"runs:/{run.info.run_id}/model", name="FabGuard_Bottleneck_Model")
        print("Model successfully registered to MLflow Registry.")
        
        # Save tg_minmax_stats.csv as artifact for Inference Pipeline
        stats_csv_path = PROCESSED_DIR / "tg_minmax_stats.csv"
        if stats_csv_path.exists():
            mlflow.log_artifact(str(stats_csv_path))
            
if __name__ == "__main__":
    run_training_pipeline()