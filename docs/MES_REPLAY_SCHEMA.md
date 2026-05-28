# DEPRECATED — MES Schedule Replay (V1)

> **Superseded by [MES_FORWARD_WHATIF_SCHEMA.md](MES_FORWARD_WHATIF_SCHEMA.md)** and `sql/flyway/V002__mes_forward_whatif.sql`.

입력용 MES 스케줄을 Postgres에 적재하고, FabEnv `DISPATCH_MODE=mes_replay`(예정)로 재현하는 스키마입니다. **(V1 — no longer 1st-class)**  
기존 `simulation_log` 등 **결과 로그는 변경하지 않음** — 계획 vs 실적은 뷰 `v_schedule_adherence`로 비교.

| 산출물 | 경로 |
|--------|------|
| Flyway DDL | `simulation/sql/flyway/V001__mes_replay_schema.sql` |
| SQLAlchemy | `simulation/models.py` (`MesScenario`, …) |
| CSV 템플릿 | `simulation/sample_csv/mes_schedule_event_template.csv` |
| 예시 시드 | `simulation/sql/seed/example_mes_scenario_180min.sql` |
| ETL (스펙) | `simulation/load_mes_schedule.py` |

---

## ER diagram

```mermaid
erDiagram
    mes_scenario ||--o{ mes_schedule_event : contains
    mes_scenario ||--o{ mes_wip_snapshot : t0_wip
    mes_scenario ||--o{ mes_tool_snapshot : t0_tool
    mes_scenario ||--o{ mes_tool_queue_snapshot : t0_queue
    mes_scenario ||--o{ mes_cqt_snapshot : t0_cqt
    mes_scenario ||--o{ mes_scenario_run : executes
    simulation_run ||--o{ mes_scenario_run : links
    mes_scenario_run ||..o{ simulation_log : compares_via_view

    mes_scenario {
        varchar scenario_id PK
        float t0_sim_minute
        float horizon_minutes
        varchar mode
        varchar status
    }
    mes_schedule_event {
        bigint id PK
        varchar scenario_id FK
        varchar lot_id
        int step_seq
        varchar tool_id
        varchar event_kind
        float scheduled_time
    }
    mes_wip_snapshot {
        bigint id PK
        varchar lot_id
        varchar status
    }
    mes_tool_snapshot {
        varchar tool_id PK_per_scenario
        varchar op_state
    }
    simulation_run {
        varchar run_id PK
    }
    simulation_log {
        bigint id PK
        varchar run_id FK
        float start_time
    }
```

---

## 1) DDL

전체 DDL은 `simulation/sql/flyway/V001__mes_replay_schema.sql` 참고.

적용:

```bash
psql "$DATABASE_URL" -f simulation/sql/flyway/V001__mes_replay_schema.sql
```

또는 SQLAlchemy:

```python
from database import create_tables
from models import Base  # includes Mes* models
create_tables()
```

---

## 2) SQLAlchemy classes

`simulation/models.py`:

- `MesScenario`
- `MesScheduleEvent`
- `MesWipSnapshot`
- `MesToolSnapshot`
- `MesToolQueueSnapshot`
- `MesCqtSnapshot`
- `MesScenarioRun`

---

## 3) `simulation_log` 확장 vs adherence 뷰 (옵션 비교)

| 방식 | 장점 | 단점 |
|------|------|------|
| **A. `simulation_log`에 planned_* 컬럼 추가** | 조인 없이 한 행 비교 | 출력 스키마·CSV·`load_csv_to_db` 전부 변경 |
| **B. 뷰 `v_schedule_adherence` (권장)** | 기존 FabEnv/CSV 무변경 | `mes_scenario_run` 링크 필요, TRACK_IN만 기본 매칭 |

현재 구현: **B**. 뷰는 `TRACK_IN` 계획 ↔ `simulation_log` 실적(`start_time`, `tool_id`) 비교.

---

## 4) Validation query examples

`:scenario_id`를 실제 ID로 바꿔 실행.

### 4.1 시나리오 윈도우

```sql
SELECT scenario_id, t0_sim_minute, horizon_minutes,
       t0_sim_minute + horizon_minutes AS t_end
FROM mes_scenario
WHERE scenario_id = :scenario_id;
```

### 4.2 스케줄이 [T0, T0+x] 안에 있는지

```sql
SELECT e.id, e.lot_id, e.step_seq, e.event_kind, e.scheduled_time
FROM mes_schedule_event e
JOIN mes_scenario s ON s.scenario_id = e.scenario_id
WHERE e.scenario_id = :scenario_id
  AND e.scheduled_time NOT BETWEEN s.t0_sim_minute AND (s.t0_sim_minute + s.horizon_minutes)
ORDER BY e.scheduled_time;
```

### 4.3 `tool_id`가 마스터 `toolgroup` 대수 안인지

```sql
SELECT e.tool_id, e.tool_group
FROM mes_schedule_event e
WHERE e.scenario_id = :scenario_id
  AND e.tool_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM toolgroup tg
    WHERE tg.toolgroup_name = e.tool_group
      AND CAST(SUBSTRING(e.tool_id FROM '#([0-9]+)$') AS INTEGER)
          BETWEEN 1 AND GREATEST(1, COALESCE(tg.num_tools, 1))
  );
```

### 4.4 `(route_id, step_seq)` 마스터 존재

```sql
SELECT DISTINCT e.route_id, e.step_seq
FROM mes_schedule_event e
LEFT JOIN process_step ps
  ON ps.route_id = e.route_id AND ps.step_seq = e.step_seq
WHERE e.scenario_id = :scenario_id
  AND ps.route_id IS NULL;
```

### 4.5 동일 툴 TRACK_IN 시간 겹침 (MES가 허용하지 않으면 실패)

```sql
SELECT a.tool_id, a.lot_id AS lot_a, b.lot_id AS lot_b,
       a.scheduled_time AS t_a, b.scheduled_time AS t_b,
       a.scheduled_end_time, b.scheduled_end_time
FROM mes_schedule_event a
JOIN mes_schedule_event b
  ON a.scenario_id = b.scenario_id
 AND a.tool_id = b.tool_id
 AND a.id < b.id
 AND a.event_kind = 'TRACK_IN'
 AND b.event_kind = 'TRACK_IN'
WHERE a.scenario_id = :scenario_id
  AND a.tool_id IS NOT NULL
  AND a.scheduled_time < COALESCE(b.scheduled_end_time, b.scheduled_time + 99999)
  AND b.scheduled_time < COALESCE(a.scheduled_end_time, a.scheduled_time + 99999);
```

### 4.6 WIP 스냅샷 시각 = T0

```sql
SELECT w.lot_id, w.snapshot_time, s.t0_sim_minute,
       ABS(w.snapshot_time - s.t0_sim_minute) AS delta
FROM mes_wip_snapshot w
JOIN mes_scenario s ON s.scenario_id = w.scenario_id
WHERE w.scenario_id = :scenario_id
  AND ABS(w.snapshot_time - s.t0_sim_minute) > 0.001;
```

### 4.7 Replay run 후 adherence

```sql
SELECT adherence_status, COUNT(*) AS n
FROM v_schedule_adherence
WHERE scenario_id = :scenario_id
  AND run_id = :run_id
GROUP BY adherence_status
ORDER BY n DESC;
```

---

## 5) CSV import template (`mes_schedule_event`)

헤더 (`simulation/sample_csv/mes_schedule_event_template.csv`):

| 컬럼 | 필수 | 설명 |
|------|------|------|
| scenario_id | Y | |
| seq | N | 동시각 tie-break, default 0 |
| lot_id | Y | |
| product | N | |
| route_id | Y | |
| step_seq | Y | |
| step_name | N | |
| tool_group | Y* | TRACK_IN 시 |
| tool_id | Y* | `TG#k` 형식 |
| event_kind | Y | `TRACK_IN` 등 |
| scheduled_time | Y | **절대 sim 분** |
| scheduled_arrive_time | N | |
| scheduled_end_time | N | |
| proc_time_planned | N | 있으면 분포 대신 고정 가공 |
| setup_id | N | |
| priority | N | |
| due_date_sim | N | |
| wafers_per_lot | N | |
| is_frozen | N | default true |
| mes_row_hash | N | idempotent upsert |
| source_line_no | N | |

\* `event_kind=TRACK_IN` 일 때 `tool_group`, `tool_id` 필수 (앱 검증).

---

## 6) Example scenario (3 lots, 2 tools, 180 min)

`simulation/sql/seed/example_mes_scenario_180min.sql` — `t0=10800`, `horizon=180`.

---

## 7) ETL CLI spec (`load_mes_schedule.py`)

```bash
.venv/bin/python load_mes_schedule.py \
  --scenario-id MES_DEMO_180 \
  --csv ./sample_csv/mes_schedule_event_template.csv \
  --t0 10800 \
  --horizon 180 \
  --mode REPLAY \
  --validate-only

# WIP / tool snapshots (optional)
.venv/bin/python load_mes_schedule.py \
  --scenario-id MES_DEMO_180 \
  --wip-csv ./wip_t0.csv \
  --tool-csv ./tool_t0.csv
```

검증 통과 시 `mes_scenario.status = VALIDATED`.

---

## 8) FabEnv 연동 (구현 예정)

```python
# reset(options={"scenario_id": "MES_DEMO_180"})
# 1) load mes_scenario, mes_wip_snapshot, mes_tool_snapshot, mes_tool_queue_snapshot
# 2) sim_env.now = t0_sim_minute
# 3) skip lot_release if mode == REPLAY
# 4) DISPATCH_MODE=mes_replay → _dispatch_for_tool picks next mes_schedule_event
#    for tool_id where event_kind=TRACK_IN and scheduled_time <= now
# 5) step until sim_env.now >= t0 + horizon_minutes
```

---

## 9) Open questions for MES team

1. **`scheduled_time` 정의**: Queue arrive vs Track-in vs Ready 중 무엇인가? `ARRIVE_QUEUE` / `TRACK_IN` 중 어떤 행에 넣을지?
2. **툴 고정 수준**: TG만 vs `tool_id`(TG#k)까지 항상 고정인가?
3. **가공시간**: `proc_time_planned` / `scheduled_end_time`을 MES가 항상 주는가, 시뮬이 `process_step` 분포로 채울 수 있는가?
4. **T0 RUN 중 Lot**: `processing_remaining_min`을 MES가 주는가, 시뮬이 역산하는가?
5. **HOLD/RELEASE**: step당 여러 번 가능한가 → `mes_row_hash` + `seq`만으로 관리?
6. **시각 좌표**: 절대 sim 분만 vs T0=0 상대 — 현재 DB는 **절대**; 상대는 `scheduled_time - t0_sim_minute` 뷰로 제공?
7. **동시 TRACK_IN**: 한 툴에 겹치는 계획을 MES가 허용하는가 (배치/다챔버)?
8. **신규 Lot 투입**: x분 구간에 fab 외부 release가 있으면 `mes_schedule_event`에 `ARRIVE_QUEUE`로 넣는가, 별도 release 테이블?
9. **PM/BD**: MES 캘린더가 있으면 `mes_schedule_event`에 넣을지, 마스터 stochastic 유지할지?
10. **WHATIF**: `REPLAY_WHATIF`에서 frozen=false 행만 엔진이 override 가능한가?
