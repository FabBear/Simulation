pipeline {
    agent any
    
    environment {
        PYTHONPATH = "${WORKSPACE}/simulation"
        // Docker 내부에서 Mac 호스트의 DB에 접속하기 위한 특수 주소
        POSTGRES_HOST = "host.docker.internal"
        POSTGRES_PORT = "5432"
        POSTGRES_USER = "postgres"
        POSTGRES_PASSWORD = "postgres"
        POSTGRES_DB = "postgres"
    }

    stages {
        stage('Checkout') {
            steps {
                echo 'Checking out source code...'
                checkout scm
            }
        }
        
        stage('Install Dependencies') {
            steps {
                echo 'Installing Python dependencies...'
                sh '''
                python3 -m venv .venv
                .venv/bin/pip install --no-cache-dir -r simulation/requirements.txt
                .venv/bin/pip install mlflow xgboost scikit-learn pandas requests shap pyarrow
                '''
            }
        }
        
        stage('Data Preprocessing') {
            steps {
                echo 'Running Data Preprocessing...'
                // TODO: data_preprocessing.py 내부가 PostgreSQL을 읽어오도록 수정되어야 합니다.
                sh '.venv/bin/python simulation/ML/data_preprocessing.py'
            }
        }
        
        stage('Model Training & Logging') {
            steps {
                echo 'Training XGBoost Model and Registering to MLflow...'
                sh '.venv/bin/python simulation/ML/train_model.py'
            }
        }
        
        stage('Model Validation & Promotion') {
            steps {
                echo 'Validating newly trained model and promoting to Production...'
                // 모델의 지표를 평가하여 통과 시에만 Production으로 승격합니다. 실패 시 파이프라인 중단.
                sh '.venv/bin/python simulation/ML/validate_model.py'
            }
        }
    }
    
    post {
        success {
            echo 'Pipeline executed successfully. Notifying Backend...'
            // TODO: 프론트엔드 알림 전송을 위한 백엔드 API (Webhook) 호출
            // 백엔드 팀과 협의 후 엔드포인트 URL과 Payload 포맷을 맞추세요.
            sh '''
            curl -X POST http://backend-server/api/webhook/mlops \
                 -H "Content-Type: application/json" \
                 -d '{"status": "SUCCESS", "message": "모델 재학습 및 MLflow 등록이 완료되었습니다."}'
            '''
        }
        failure {
            echo 'Pipeline failed. Sending failure notification...'
            sh '''
            curl -X POST http://backend-server/api/webhook/mlops \
                 -H "Content-Type: application/json" \
                 -d '{"status": "FAILED", "message": "MLOps 파이프라인 실행 중 오류가 발생했습니다."}'
            '''
        }
    }
}