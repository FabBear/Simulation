# FAB_BEAR

FabGuard PoC용 **배치 시뮬 + CSV/KPI 파이프라인** 분리 프로젝트입니다.  
원본: `Final_Project/Simulation` (프론트/K8s 제외).

## 구조

```text
FAB_BEAR/
  simulation/          # FabEnv, run_sim_csv_once.py, init_db.py, data/
  spring-backend/      # 보관용 (당장 미사용 가능)
  docs/README_DOCKER.md
  docker-compose.yml   # Postgres only
  .env.example
```

## 빠른 시작

```bash
cd /path/to/FAB_BEAR
cp .env.example .env
docker compose up -d db

cd simulation
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python init_db.py    # 전용 DB 권장 (drop_all). ProcessStep CQT 컬럼 변경 시 재실행 필수

export SIM_CSV_DIR=./sim_csv_out
export SIM_END_MINUTES=2000
export KPI_INSTANT_PERIOD_MIN=60
.venv/bin/python run_sim_csv_once.py --csv-dir ./sim_csv_out --end-minutes 2000 --max-steps 500
```

출력 CSV 7종: `simulation_process`, `lot_events`, `tool_state`, `kpi_fab`, `kpi_process`, `kpi_toolgroup`, `kpi_tool`.

### CSV → DB 적재

```bash
cd simulation
.venv/bin/python load_csv_to_db.py --csv-dir ./sim_csv_out
# 기존 run_id 덮어쓰기: --truncate-run
```

매핑 상세: [docs/CSV_DB_MAPPING.md](docs/CSV_DB_MAPPING.md)  
KPI 4종 CSV 가이드: [docs/KPI_CSV_4FILES.md](docs/KPI_CSV_4FILES.md)

## 환경 파일

`simulation/database.py` loads (in order):

1. `FAB_BEAR/.env`
2. `Final_Project/.env` (parent of FAB_BEAR)

## 제외된 것 (원본 Simulation에만 있음)

- `fab-dashboard/`, `ingress.yaml`, K8s manifests
- PPO `logs/*.zip`
- `SMT_2020 - Final/` AutoSched 데이터
- `backend_manager.py`, `main_api.py` (Digital Twin API)
- V1 MES REPLAY schedule grid (`mes_schedule_event` TRACK_IN) — see V2 `docs/MES_FORWARD_WHATIF_SCHEMA.md`

## 다음 단계

What-if 시뮬: `simulation/core/`, `simulation/schemas/` (스냅샷 + action + 부분 스케줄 + KPI).

자세한 실행·Docker: [docs/README_DOCKER.md](docs/README_DOCKER.md) · KPI: [docs/KPI_CSV_4FILES.md](docs/KPI_CSV_4FILES.md)
