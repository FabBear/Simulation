# CSV ↔ DB 매핑 (SSOT)

FabEnv가 `sim_csv_out`에 쓰는 CSV 7종과 PostgreSQL 로그 테이블의 컬럼 대응입니다.  
적재 스크립트: `simulation/load_csv_to_db.py` · 매핑 코드: `simulation/csv_db_mapping.py`

## run_id 정책 (옵션 A)

| 항목 | 설명 |
|------|------|
| `simulation_run` | 에피소드 메타 (`run_id` PK) |
| 로그 4테이블 | `run_id VARCHAR` (nullable — 구 FabEnv row 호환) |
| CSV | 모든 파일에 `run_id` 컬럼 |
| FabEnv | DB insert 시 `self._csv_run_id` 기록 |

## 1. simulation_process.csv → simulation_log

| CSV | DB | 변환 |
|-----|-----|------|
| run_id | run_id | |
| lot_id | lot_id | |
| product | product | |
| route_id | route_id | |
| step_seq | step_seq | int |
| step_name | step_name | |
| tool_group | tool_group | |
| tool_id | tool_id | `""` → NULL |
| arrive_time | arrive_time | float |
| start_time | start_time | |
| end_time | end_time | |
| queue_time | queue_time | |
| process_time | process_time | |
| event_type | event_type | |

## 2. lot_events.csv → lot_event_log

| CSV | DB |
|-----|-----|
| run_id | run_id |
| lot_id | lot_id |
| product | product |
| route_id | route_id |
| step_seq | step_seq |
| tool_group | tool_group |
| tool_id | tool_id (`""` → NULL) |
| event_type | event_type |
| event_time | event_time |
| detail_1 | detail_1 |
| detail_2 | detail_2 |

## 3. tool_state.csv → tool_state_log

| CSV | DB |
|-----|-----|
| run_id | run_id |
| tool_group | tool_group |
| tool_id | tool_id (`""` → NULL, 집계 행) |
| state | state |
| state_change_time | state_change_time |
| setup_name | setup_name |
| lot_id | lot_id |
| reason | reason |
| idle_units … down_bm_units | 동명 |

## 4. KPI CSV → kpi_snapshot

| CSV 파일 | DB `level` |
|----------|------------|
| kpi_fab.csv | FAB |
| kpi_process.csv | PROCESS |
| kpi_toolgroup.csv | TOOLGROUP |
| kpi_tool.csv | TOOL |

| CSV | DB |
|-----|-----|
| run_id | run_id |
| snapshot_time | snapshot_time |
| — | level ← 파일명 |
| scope | scope |
| kpi_name | kpi_name |
| value | value |
| window_minutes | window_minutes (`""` → NULL) |
| numerator | numerator |
| denominator | denominator |
| meta | meta |

## CSV-only / DB-only

| 구분 | 항목 |
|------|------|
| CSV만 | (없음 — run_id는 DB에도 저장) |
| DB만 | `active_cqt_timer`, `realtime_wip_summary` |
| KPI CSV | `level` 컬럼 없음 (파일명으로 유도) |

## FabEnv 런타임 vs CSV import

| 경로 | run_id | KPI level |
|------|--------|-----------|
| FabEnv → DB | `_csv_run_id` | 코드에서 설정 |
| FabEnv → CSV | 동일 | 파일 분할 |
| load_csv_to_db | CSV `run_id` | 파일명 → level |

## 마이그레이션

- Flyway: `spring-backend/.../V5__simulation_run_and_run_id.sql`
- Python only: `simulation/sql/V5__...` (loader가 자동 적용, `--skip-schema`로 생략 가능)

## 사용 예

```bash
cd FAB_BEAR/simulation
.venv/bin/python load_csv_to_db.py --csv-dir ./sim_csv_out
.venv/bin/python load_csv_to_db.py --csv-dir ./sim_csv_out --truncate-run --run-id abc123
```
