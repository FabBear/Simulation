// ② 라벨링 스케줄 잡: 15분마다 T0+120 도달분의 is_bottleneck_true를 채운다.
// Jenkins 잡 생성: New Item → Pipeline → Pipeline script from SCM
//   SCM=MLOps repo, Branch=*/dev, Script Path=simulation/ML/Jenkinsfile.labeling.groovy
pipeline {
    agent any

    // 15분마다 라벨링 (cron 트리거)
    triggers { cron('H/15 * * * *') }

    // 중복 실행 가드 (라벨링끼리 겹치지 않게)
    options { disableConcurrentBuilds() }

    environment {
        PYTHONPATH = "${WORKSPACE}/simulation"
        // Docker 내부 → Mac 호스트 DB
        POSTGRES_HOST = "host.docker.internal"
        POSTGRES_PORT = "5432"
        POSTGRES_USER = "fabbear_user"
        POSTGRES_PASSWORD = "fabbear_pw"
        POSTGRES_DB = "fabbear"
        POSTGRES_SCHEMA = "simulation"
        MLFLOW_TRACKING_URI = "http://host.docker.internal:5500"
    }

    stages {
        stage('Checkout') {
            steps { checkout scm }
        }
        stage('Install Dependencies') {
            steps {
                sh '''
                python3 -m venv .venv
                .venv/bin/pip install --no-cache-dir -r simulation/requirements.txt
                .venv/bin/pip install --no-cache-dir pandas sqlalchemy psycopg2-binary
                '''
            }
        }
        stage('Label Predictions (T0+120)') {
            steps {
                // 미라벨 예측에 학습과 동일한 룰/임계값으로 is_bottleneck_true UPDATE
                sh '.venv/bin/python simulation/ML/label_predictions.py'
            }
        }
    }

    post {
        failure { echo 'Labeling batch failed. Check logs.' }
    }
}
