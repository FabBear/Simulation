# FAB_BEAR — Python 시뮬·DB·CSV 가이드

이 문서는 **배치 FabEnv → CSV 7종** 파이프라인용입니다.  
프론트엔드(`fab-dashboard`), K8s/ingress, full-stack docker-compose는 **원본 `Final_Project/Simulation`** 을 참고하세요.

## 1) Postgres만 기동

```bash
cd /path/to/FAB_BEAR
docker compose up -d db
```

- `FAB_BEAR/.env`의 `POSTGRES_*` 값을 사용합니다.
- Spring Flyway는 **선택** (`spring-backend/` 보관). Python만 쓸 때는 `init_db.py`가 ORM 테이블을 생성합니다.

### 스키마 운영 규칙

- **스키마 SSOT**: `simulation/models.py`
- **`init_db.py`는 `drop_all` 포함** — 전용 개발 DB 권장. Spring Flyway와 같은 DB를 쓰지 마세요.
- **순서**: `docker compose up -d db` → `simulation/init_db.py` → `run_sim_csv_once.py`

## 2) 중지 / DB 초기화

```bash
docker compose down
docker compose down -v   # 볼륨 삭제
```

---

## 3) Python 시뮬(FabEnv) — CSV 출력·DB 로그

`FAB_BEAR/simulation`에서 `run_sim_csv_once.py`를 실행합니다.  
`FabEnv.reset()`은 DB 마스터를 읽고, `SIM_CSV_DIR`가 설정되면 CSV에도 기록합니다.

### 3-1) 사전 준비

- **연결**: `simulation/database.py`는 `FAB_BEAR/.env` → `Final_Project/.env`(상위) 순으로 로드합니다.
- **마스터 데이터**: `simulation/data/*.xlsx` → `init_db.py`

```bash
cd /path/to/FAB_BEAR/simulation
../.venv/bin/python init_db.py   # 또는 simulation/.venv
```

### 3-2) 환경변수 요약

| 변수 | 의미 |
|------|------|
| `SIM_CSV_DIR` | 출력 디렉터리 (`simulation/sim_csv_out` 등) |
| `SIM_END_MINUTES` | 시뮬 종료 시각(분) |
| `SIM_CSV_MAX_STEPS` | Gym step 상한 |
| `DISPATCH_MODE` | `rule`(기본) |
| `KPI_INSTANT_PERIOD_MIN` | 순간 KPI 주기: `rtf`, `completion_rate`, `wip`, `q_time_min` |
| `KPI_UTIL_WINDOW_MIN` / `KPI_TAT_WINDOW_MIN` / `KPI_THROUGHPUT_WINDOW_MIN` | 윈도우 KPI |

### 3-3) CSV 배치 실행 (예시)

```bash
cd /path/to/FAB_BEAR/simulation
export DISPATCH_MODE=rule
export SIM_CSV_DIR=./sim_csv_out
export SIM_END_MINUTES=2000
export KPI_INSTANT_PERIOD_MIN=60
.venv/bin/python run_sim_csv_once.py --csv-dir ./sim_csv_out --end-minutes 2000 --max-steps 500
```

### 3-4) 생성되는 CSV (7종)

| 파일 | 설명 |
|------|------|
| `simulation_process.csv` | Lot·스텝 처리 완료 |
| `lot_events.csv` | Lot 이벤트 |
| `tool_state.csv` | ToolGroup 집계 + unit 행 |
| `kpi_fab.csv` | FAB KPI (`rtf`, `completion_rate`, …) |
| `kpi_process.csv` | Process KPI |
| `kpi_toolgroup.csv` | ToolGroup KPI |
| `kpi_tool.csv` | Tool KPI |

### 3-5) KPI (요약)

| 레벨 | 순간 KPI | 윈도우 KPI |
|------|----------|------------|
| FAB | `rtf`, `completion_rate`, `wip`, `q_time_min` | `utilization`, `tat_min`, `throughput_24h` |
| PROCESS | `wip`, `q_time_min` | `utilization`, `performance`, `quality`, `oee_estimate` |
| TOOLGROUP | `available_tool_ratio`, `wip`, … | `utilization_avg`, `setup_ratio_avg` |
| TOOL | `q_len`, … | `utilization`, `performance`, `quality`, `oee_estimate` |

### 3-6) 검증 예시

```bash
cd /path/to/FAB_BEAR/simulation
rm -rf ./sim_csv_kpi_check
DISPATCH_MODE=rule SIM_CSV_DIR=./sim_csv_kpi_check SIM_END_MINUTES=500 \
KPI_INSTANT_PERIOD_MIN=60 \
.venv/bin/python run_sim_csv_once.py --end-minutes 500 --max-steps 600 --sort-csv
```
