#!/bin/bash
set -e

echo "🚀 Starting FabGuard MLOps E2E Integration Test..."

echo "----------------------------------------"
echo "[1/5] Running Data Preprocessing..."
python simulation/ML/data_preprocessing.py

echo "----------------------------------------"
echo "[2/5] Running Model Training & Logging..."
python simulation/ML/train_model.py

echo "----------------------------------------"
echo "[3/5] Running Model Validation (Gatekeeper)..."
python simulation/ML/validate_model.py

echo "----------------------------------------"
echo "[4/5] Running Production Inference at T0..."
python simulation/ML/ml_g_star_at_t0.py

echo "----------------------------------------"
echo "[5/5] Running Model Drift Evaluation..."
python simulation/ML/evaluate_model_drift.py

echo "----------------------------------------"
echo "✅ MLOps E2E Integration Test completed successfully!"