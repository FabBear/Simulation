// ③ 드리프트 평가 스케줄 잡: 라벨 누적분으로 F1을 계산해 임계 미달 시 재학습 트리거.
// Jenkins 잡 생성: New Item → Pipeline → Pipeline script from SCM
//   SCM=MLOps repo, Branch=*/dev, Script Path=simulation/ML/Jenkinsfile.drift.groovy
// 사전 준비: Jenkins 자격증명(Username with password)으로 'jenkins-api-token' 등록
//   (Username=Jenkins 사용자, Password=API Token) → 재학습 잡 트리거 인증용.
pipeline {
    agent any

    // 매일 새벽 2시 드리프트 평가 (필요 시 'H H/6 * * *' 등으로 조정)
    triggers { cron('H 2 * * *') }

    options { disableConcurrentBuilds() }

    environment {
        PYTHONPATH = "${WORKSPACE}/simulation"
        POSTGRES_HOST = "host.docker.internal"
        POSTGRES_PORT = "5432"
        POSTGRES_USER = "fabbear_user"
        POSTGRES_PASSWORD = "fabbear_pw"
        POSTGRES_DB = "fabbear"
        POSTGRES_SCHEMA = "simulation"
        // 컨테이너 → 호스트 Jenkins(8081)
        JENKINS_URL = "http://host.docker.internal:8081"
        DRIFT_THRESHOLD = "0.70"
        DRIFT_MIN_SAMPLES = "50"
        DRIFT_EVAL_WINDOW_HOURS = "24"
        RETRAIN_COOLDOWN_SEC = "3600"
    }

    stages {
        stage('Checkout') {
            steps { checkout scm }
        }
        stage('Install Dependencies') {
            steps {
                sh '''
                python3 -m venv .venv
                .venv/bin/pip install --no-cache-dir pandas sqlalchemy psycopg2-binary scikit-learn requests
                '''
            }
        }
        stage('Evaluate Drift & Trigger Retrain') {
            steps {
                // 재학습 잡 트리거 인증 토큰 주입 (CSRF crumb는 스크립트가 처리)
                withCredentials([usernamePassword(
                    credentialsId: 'jenkins-api-token',
                    usernameVariable: 'JENKINS_USER',
                    passwordVariable: 'JENKINS_TOKEN'
                )]) {
                    sh '.venv/bin/python simulation/ML/evaluate_model_drift.py'
                }
            }
        }
    }

    post {
        failure { echo 'Drift evaluation failed. Check logs.' }
    }
}
