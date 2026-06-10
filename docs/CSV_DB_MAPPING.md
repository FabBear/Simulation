# CSV ↔ DB 매핑 (SSOT)

FabEnv가 `sim_csv_out`에 쓰는 CSV 7종과 PostgreSQL 로그 테이블의 컬럼 대응입니다.  
적재 스크립트: `simulation/load_csv_to_db.py` · 매핑 코드: `simulation/csv_db_mapping.py`

## PostgreSQL schema

| 항목 | 값 |
|------|-----|
| Platform SSOT | `POSTGRES_SCHEMA=simulation` (`simulation/schema_config.py`) |
| Local default port | `5433` (`FAB_BEAR/.env`) |
| Qualified example | `simulation.kpi_tool`, `simulation.lot_event_log` |

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

## 4. KPI CSV → level별 테이블 (V6)

| CSV 파일 | DB 테이블 |
|----------|-----------|
| kpi_fab.csv | `kpi_fab` |
| kpi_process.csv | `kpi_process` |
| kpi_toolgroup.csv | `kpi_toolgroup` |
| kpi_tool.csv | `kpi_tool` |

| CSV | DB (4테이블 공통) |
|-----|-------------------|
| run_id | run_id |
| snapshot_time | snapshot_time |
| scope | scope |
| kpi_name | kpi_name |
| value | value |
| window_minutes | window_minutes (`""` → NULL) |
| numerator | numerator |
| denominator | denominator |
| meta | meta |

레거시 통합 조회: `kpi_snapshot` **VIEW** (`level` 컬럼 포함, 읽기 전용). Flyway `V6__kpi_level_tables.sql`.

## 5. lot_release_ledger.csv → lot_release_ledger

| CSV | DB |
|-----|-----|
| run_id | run_id |
| scenario_id | scenario_id (`""` → NULL) |
| lot_id | lot_id |
| lot_type | lot_type |
| product_name | product_name |
| route_name | route_name |
| sim_now_min | sim_now_min |
| due_date_sim_min | due_date_sim_min |
| priority | priority |
| is_super_hot | is_super_hot (0/1/true → bool) |
| wafers_per_lot | wafers_per_lot |
| source | source |

## CSV-only / DB-only

| 구분 | 항목 |
|------|------|
| CSV만 | (없음 — run_id는 DB에도 저장) |
| DB만 | `active_cqt_timer`, `realtime_wip_summary` |
| KPI CSV | `level` 컬럼 없음 (파일명으로 유도) |

## FabEnv 런타임 vs CSV import

| 경로 | run_id | KPI level |
|------|--------|-----------|
| FabEnv → DB | `_csv_run_id` | level별 테이블 라우팅 |
| FabEnv → CSV | 동일 | 파일 분할 |
| load_csv_to_db | CSV `run_id` | 파일명 → 테이블 |

## 마이그레이션

- Flyway: `spring-backend/.../V5__simulation_run_and_run_id.sql`
- Python only: `simulation/sql/V5__...` (loader가 자동 적용, `--skip-schema`로 생략 가능)

## 사용 예

```bash
cd FAB_BEAR/simulation
.venv/bin/python load_csv_to_db.py --csv-dir ./sim_csv_out
.venv/bin/python load_csv_to_db.py --csv-dir ./sim_csv_out --truncate-run --run-id abc123
```
