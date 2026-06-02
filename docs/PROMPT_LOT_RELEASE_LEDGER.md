# Task: `lot_release_ledger.csv` + DB 적재 (release 시 1회 스냅샷)

## 목적

`run_sim_forward_once.py` / `FabEnv` 실행 시, **lot이 fab에 release되는 순간** 메타데이터를 **한 번만** 기록한다.

- **8번째 CSV**: `sim_csv_out/lot_release_ledger.csv`
- **DB**: 동일 행을 `lot_release_ledger` 테이블에 insert
- **비목표**: T0 WIP 시드 행, `rem_steps` 저장, release마다 갱신
- **Agent 용도**: `due_date_sim_min` + T0 `mes_wip_snapshot.rem_steps` join → T0 시점 CR 계산

---

## 질문: `lot_events.csv` ARRIVAL `detail_2` JSON 제거해도 되나?

| 답 | 내용 |
|----|------|
| **신규 run (ledger 있음)** | **가능.** release due/메타 SSOT를 ledger로 옮기면 ARRIVAL `detail_2`의 release JSON은 **중복** |
| **권장** | ARRIVAL **이벤트 자체는 유지** (`event_type=ARRIVAL`, `event_time`). `detail_2`는 `NULL` 또는 `detail_1`만 `release_time` 등 최소 |
| **주의** | `tools/build_forward_scenario_from_csv.py`가 today `lot_events` ARRIVAL `detail_2.due_date_sim_min`을 읽음 → **ledger 우선, detail_2 fallback** 으로 수정 필요 (본 task 범위에 포함 권장) |
| **하위 호환** | 구 run CSV 재처리 시 ledger 없으면 기존 `detail_2` 파싱 유지 |

**정리:** ledger 도입 후 **새 코드 경로에서는 detail_2 release JSON 추가 안 해도 됨.** 단, 역추정 ETL 한 줄은 같이 고칠 것.

---

## Release 1회 기록 시점 (FabEnv hook)

다음 경로에서 **실제 lot 프로세스 spawn 직전/직후 1회** `_log_lot_release_ledger(...)` 호출:

1. **`_source_process` → `_release_one_lot`**  
   - `mes_lot_release_plan` / master `LotRelease` / `_LotReleaseLike` adapter 공통
2. **Cold-start master release** (`reset` 시 `_source_process(r)` spawn) — scenario 없을 때만

**기록하지 않음 (Locked):**

- **T0 `mes_wip_snapshot` 시드** (`_inject_wip_snapshot` / `_lot_process_from`) — release 이벤트 없음. T0 CR은 **`mes_wip`만** 사용.
- 동일 lot 재입장, rework spawn 등

---

## 출력 스키마

### CSV: `lot_release_ledger.csv`

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `run_id` | string | `FabEnv._csv_run_id` (기존 로그와 동일) |
| `scenario_id` | string | `mes_scenario.scenario_id` (없으면 `""`) |
| `lot_id` | string | lot name |
| `lot_type` | string | `LotRelease.lot_type` / plan `lot_type` (없으면 `""`) |
| `product_name` | string | |
| `route_name` | string | |
| `sim_now_min` | float | **절대 fab 분** = `sim_env.now + _sim_clock_offset` (다른 CSV와 동일 convention) |
| `due_date_sim_min` | float | 절대 fab 분 (`_lot_process`에 넘기는 due와 동일 기준) |
| `priority` | int | |
| `is_super_hot` | bool/int | 0/1 |
| `wafers_per_lot` | int | |
| `source` | string | `mes_plan` \| `master` \| `cold_start` (디버그용, 선택) |

**넣지 않음:** `rem_steps`, `remaining_to_due_min` (계산 가능), `remaining_to_due` JSON

### DB: `lot_release_ledger`

- `models.py`에 `LotReleaseLedger` (또는 `SimLotReleaseLog`) 추가
- 컬럼 = CSV와 1:1
- 인덱스: `(run_id)`, `(scenario_id, lot_id)` unique 권장 (동일 run에서 lot_id 중복 방지)

### Migration

- FAB_BEAR에 Flyway 없으면: `init_db.py` / 수동 DDL 문서 + `Base.metadata.create_all` 경로에 테이블 추가
- 기존 `lot_event_log` / `simulation_log` 패턴 따름

---

## 구현 지침 (`fab_env.py`)

### 1) 상수

```python
_SIM_CSV_LOT_RELEASE_LEDGER_FIELDS = (
    "run_id", "scenario_id", "lot_id", "lot_type", "product_name", "route_name",
    "sim_now_min", "due_date_sim_min", "priority", "is_super_hot", "wafers_per_lot", "source",
)
```

### 2) 헬퍼 `_log_lot_release_ledger(...)`

- `_log_lot_event` / `_log_process`와 동일: `SessionLocal` → `db.add` → `commit` → `_append_sim_csv`
- `sim_now_min` = `float(self._sim_now_abs())`
- `due_date_sim_min` = `float(due_date) + float(self._sim_clock_offset)`  
  (상대 due를 쓰는 경로면 offset 더해 **절대분**으로 통일 — `lot_events` ARRIVAL `detail_2`와 동일)

### 3) Hook

`_release_one_lot(lot_due_date)` 내부, `_lot_process(...)` 호출 **직전 또는 직후**:

```python
self._log_lot_release_ledger(
    lot_id=lot_name,
    lot_type=...,
    product_name=r.product_name,
    route_name=r.route_name,
    due_date_sim_min=...,  # absolute
    priority=int(r.priority or 0),
    is_super_hot=is_super,
    wafers_per_lot=wafers,
    source="mes_plan" or "master",
)
```

`scenario_id`: `self._mes_scenario_id` (이미 FabEnv에 있으면 사용, 없으면 env `SIM_SCENARIO_ID`)

### 4) ARRIVAL `detail_2` 정리

`_lot_process` ARRIVAL 블록:

- **Before:** `detail_2=json.dumps({sim_now_min, due_date_sim_min, remaining_to_due_min})`
- **After:** `detail_2=None` (또는 필드 제거)
- `detail_1`은 optional 유지 (`str(sim_now_min)`)

### 5) `run_sim_forward_once.py`

- 변경 최소 (FabEnv만으로 CSV 생성됨)
- 종료 로그에 한 줄 추가: `lot_release_ledger rows: <count>` (optional, `env._kpi_release_count`와 대조)

---

## ETL follow-up (`build_forward_scenario_from_csv.py`)

| 우선순위 | 소스 |
|----------|------|
| 1 | `lot_release_ledger.csv` — `lot_id`, `sim_now_min`, `due_date_sim_min`, `product_name`, `route_name`, … |
| 2 (fallback) | `lot_events.csv` ARRIVAL `detail_2.due_date_sim_min` |

`mes_lot_release_plan.due_date_sim` / release_time 역추정 시 ledger 컬럼 사용.

---

## 테스트

`FAB_BEAR/simulation/tests/test_lot_release_ledger.py` (신규):

1. **Scenario FORWARD stub**: `MesLotReleasePlan` 1건 → run 짧게 → CSV에 1행, `due_date_sim_min` 일치
2. **중복 없음**: 동일 lot 1 release → ledger 1행 (WIP inject는 0행)
3. **ARRIVAL**: `lot_events`에 ARRIVAL 존재, `detail_2` empty/NULL (ledger 도입 후)

기존 `test_tool_wakeup_and_superhot.py` / smoke regression 유지.

---

## 문서

- `docs/SMT2020_DISPATCH.md` 또는 `docs/REPORT_SIMULATION_KPI.md`에 산출물 8종 목록 업데이트
- Agent 계약 한 줄:  
  `CR(lot,T0) = (due_date_sim_min - T0) / rem_steps`  
  due ← `lot_release_ledger` ⋈ `mes_wip_snapshot` on `lot_id`

---

## Acceptance checklist

- [x] `sim_csv_out/lot_release_ledger.csv` 생성 (FORWARD 1 run)
- [x] Postgres `lot_release_ledger` 동일 행
- [x] 컬럼: lot_id, lot_type, product, route, sim_now_min, due_date_sim_min, priority, super_hot, wafers
- [x] release 1회 = 1행; T0 WIP 시드는 0행
- [x] ARRIVAL `detail_2` release JSON 제거
- [x] `build_forward_scenario_from_csv` ledger 우선 읽기
- [x] pytest green

---

## 비목표 (이번 task)

- T0 WIP용 ledger backfill
- `rem_steps` / CR을 ledger에 저장
- Spring backend / Agent API 변경 (CSV·DB만 제공)
