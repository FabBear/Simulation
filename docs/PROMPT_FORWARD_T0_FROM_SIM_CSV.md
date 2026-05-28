# Task: `run_sim_forward_once.py` 실행을 위한 MES 시나리오 데이터 구축 (CSV 역추정)

## 목적

기존 cold-start 시뮬레이션 결과(`sim_csv_out/`)와 Postgres 마스터를 이용해, **FORWARD 시나리오**를 DB에 적재하고 `simulation/run_sim_forward_once.py`를 실행할 수 있게 한다.

- **범위**: T0 스냅샷 3종 + `mes_lot_release_plan` + `mes_scenario` 메타. **`mes_cqt_snapshot`은 이번 task에서 제외** (0행 허용).
- **비목표**: 원 run과 bit-identical 재현, `mes_whatif_action` (WHAT-IF는 별도 task), Trigger/ML 자동화.
- **품질 기대**: PoC / 데모 / “같은 run 궤적을 대략 이어가기”. 정합이 critical하면 T0 시점 **FabEnv 메모리 export**가 SSOT (본 prompt는 CSV 역추정 경로).

---

## Runner 계약 (반드시 지킬 것)

| 항목 | 내용 |
|------|------|
| 실행기 | `FAB_BEAR/simulation/run_sim_forward_once.py --scenario-id <ID>` |
| DB | Postgres + `init_db.py`로 마스터(`ProcessStep`, `ToolGroup`, `LotRelease`, …) 로드됨 |
| 시나리오 상태 | **`mes_scenario.status = 'VALIDATED'`** 만 실행 (`DRAFT`는 거부) |
| CSV 입력 | Runner는 **CSV를 읽지 않음**. 모든 입력은 **DB `mes_*` 테이블** |
| ETL | `simulation/load_mes_scenario.py` 또는 동등 SQL/스크립트로 CSV → DB |
| 시뮬 시계 | `mes_scenario.t0_sim_minute` = 절대 fab 분. SimPy는 `0..horizon`. 로그 시각 = `sim_env.now + t0` |
| Master release | **`use_master_lot_release = false`** (기본 권장). master `LotRelease`는 **마스터 참조용만**, 자동 spawn 안 함 |

엔진 inject 순서 (`fab_env._apply_scenario_overrides`):

1. `mes_tool_snapshot`
2. `mes_tool_queue_snapshot` (WIP보다 **먼저**)
3. `mes_wip_snapshot`
4. `mes_cqt_snapshot` (0행 OK)
5. (WHAT-IF만) `mes_whatif_action`
6. `mes_lot_release_plan`

**Locked**: queue에 있는 lot은 **`mes_wip_snapshot`에도 반드시 포함** (queue inject 시 `product`/`rem_steps` 기본값 방지).

---

## 입력 SSOT (같은 run_id로 정렬)

| 소스 | 경로/테이블 | 용도 |
|------|-------------|------|
| Raw log | `sim_csv_out/lot_events.csv` | ARRIVAL, LOADING, FINISH, … |
| Raw log | `sim_csv_out/tool_state.csv` | T0 tool `op_state`, `setup_name`, `lot_id` |
| Raw log | `sim_csv_out/simulation_process.csv` | **완료된 step** 이력만 (in-flight 부적합) |
| KPI | `sim_csv_out/kpi_tool.csv` | T0 `@ snapshot_time` 의 `q_len`, `processing_count` |
| 마스터 | Postgres `process_step`, `toolgroup`, … | step `proc_time_mean`, `target_tool_group`, dispatch |
| 마스터 | Postgres `lot_release` | `wafers_per_lot`, priority 보조 (spawn은 하지 않음) |
| 시나리오 메타 | `mes_scenario` | `t0_sim_minute`, `horizon_minutes`, `mode=FORWARD` |

**공통 필터**: `run_id = <원본 run>` AND 모든 시각은 **절대 sim 분** (`event_time`, `snapshot_time`).

---

## 1. `mes_scenario` (필수)

| 필드 | 값 |
|------|-----|
| `scenario_id` | 신규 ID (예: `FWD_FROM_RUN_<run_id_short>_<T0>`) |
| `mode` | `FORWARD` |
| `t0_sim_minute` | 역추정 기준 시각 T0 (예: KPI `snapshot_time` 또는 운영자 지정) |
| `horizon_minutes` | 전개 구간 H (예: 180, 1440) |
| `use_master_lot_release` | **`false`** |
| `status` | ETL 후 `DRAFT` → 검증 후 **`VALIDATED`** |
| `baseline_scenario_id` | WHAT-IF가 아니면 NULL |

---

## 2. `mes_tool_snapshot` (사실상 필수)

### 엔진 사용 필드

| 필드 | 출처 | 알고리즘 |
|------|------|----------|
| `tool_id` | `tool_state.csv` | `tool_id`에 `#` 포함 unit 행만. `tool_id=""` 집계 행 제외 |
| `tool_group` | 파생 | `tool_id.split('#')[0]` |
| `op_state` | `tool_state.state` | `state_change_time <= T0` per `tool_id` **마지막 행** → `IDLE`/`RUN`/`SETUP`/`DOWN_PM`/`DOWN_BM` |
| `current_setup` | `tool_state.setup_name` | 동일 마지막 행 |
| `held_lot_id` | — | 스키마만, 엔진 미사용 → NULL |

### 정확도

- **높음** (T0 장비 상태).
- **한계**: RUN 직후 아직 `tool_state` 미기록 edge case. DOWN 잔여시간은 마스터 PM/BM 통계로 엔진이 근사 (`_inject_down_hold`).

### 주의

- `mes_tool_snapshot`에는 **가공 잔여시간 없음**. 잔여는 `mes_wip.processing_remaining_min`.

---

## 3. `mes_tool_queue_snapshot` (강력 권장, 비어도 run 가능)

### 엔진 사용 필드

| 필드 | 출처 |
|------|------|
| `tool_id`, `position` | 추정 |
| `lot_id`, `step_seq`, `due_date_sim`, `priority` | queue payload / WIP |
| `route_id` | 스키마·검증용 (payload 직접 주입 X) |

### 알고리즘 (PoC)

```
1) kpi_tool @ T0: tool T → q_len = N
2) WIP 후보 lot L:
   - lot_events: ARRIVAL 있음, route 미완료
   - current step S: (L,S) FINISH 없음
   - route[S].target_tool_group → dispatch로 unit T* 결정
     (_choose_tool_for_lot 재현: wakeup, queue len, setup, LTL lock — 마스터 필요)
   - T0 tool_state: T* 에서 RUN/SETUP lot_id ≠ L
3) tool T (=T*) 별 후보를 due/priority/ARRIVAL 시각으로 정렬 → position=1..N
4) |후보| > N 이면 confidence 낮음 — KPI q_len 우선 trim
```

### 하지 말 것

- **`LOADING` 이벤트 = queue** ❌ (LOADING은 queue **탈출 후**, RUN 직후).
- **「FINISH 된 lot = queue」** ❌ (현재 step **미완료** lot만).

### 정확도

- **개수(`q_len`)**: 같은 run KPI면 **신뢰도 높음**.
- **멤버·순서**: **중간** (dispatch 재현 오차).

### batch

- Batch step 대기는 `tools[tool].queue`가 아닌 `batch_queues` → `q_len`에 **안 잡힐 수 있음**. 별도 규칙 또는 `WAIT_BATCH` 라벨.

---

## 4. `mes_wip_snapshot` (T0 fab에 lot 있으면 필수)

### 엔진 status

| status | 역추정 |
|--------|--------|
| `PROCESSING` | T0 `tool_state`: unit `RUN`/`SETUP` + `lot_id` |
| `QUEUING` | queue snapshot 행과 동일 lot |
| `HOLD` | 로그만으로 어려움 → 제외 또는 수동 |
| `WAIT_TRANSPORT` / `WAIT_BATCH` | 구분 어려움 → `QUEUING` 근사 |

### 필드별 출처

| 필드 | 출처 |
|------|------|
| `lot_id` | `lot_events` / queue / tool_state |
| `route_id`, `product` | `lot_events` |
| `current_step_seq` | T0 직전 이벤트 `step_seq`; FINISH 직후면 **다음 step** 보정 |
| `due_date_sim` | ARRIVAL `detail_2` JSON `due_date_sim_min` |
| `priority`, `is_super_hot`, `wafers_per_lot` | ARRIVAL에 없으면 master `lot_release` 또는 default |
| `rem_steps` | `len(route) - step_index` (마스터) |
| `tool_id` | PROCESSING: RUN tool. QUEUING: dispatch 추정 tool |
| `processing_remaining_min` | **추정** (아래) |
| `tool_group`, `queue_position` | 엔진 미사용 |

### `processing_remaining_min` 추정 (PROCESSING만)

**현재 step** `ProcessStep` (route + `current_step_seq`):

- `proc_std` = `proc_time_mean` (+ wafer `proc_unit` 규칙, `_compute_standard_proc_time` 동일)
- `trans_m` = transport rule `mean_time` (없으면 0)
- `total_proc_block` ≈ `proc_std + trans_m`

**시간축** (`t_load` = 해당 step 마지막 `LOADING.event_time`, `load_d` = `detail_1`):

```
elapsed = T0 - t_load
if elapsed < load_d:
  remaining = (load_d - elapsed) + setup_d + total_proc_block
elif elapsed < load_d + setup_d:
  remaining = (load_d + setup_d - elapsed) + total_proc_block
else:
  remaining = total_proc_block - (elapsed - load_d - setup_d)
processing_remaining_min = max(0, remaining)
```

- `setup_d`: T0 이전 SETUP `tool_state` 구간 또는 마스터 setup matrix.
- **없거나 ≤0** → 엔진이 T0에서 **즉시 FINISH** (§2).

### 정확도

- lot·step·route: **중~높음**
- 잔여시간: **낮~중** (실제 run은 distribution 샘플)

---

## 5. `mes_lot_release_plan` (FORWARD 의미 있으면 필수)

### 원칙

- T0 **이후** fab에 **새로 들어오는** lot = `lot_events` **`ARRIVAL`**.
- Master `LotRelease`는 DB에 있어도 **`use_master_lot_release=false`** 이면 spawn **안 함** → **이중 투입 없음**.

### ARRIVAL → plan 행 (1 ARRIVAL = 1 lot)

| plan 필드 | 매핑 |
|-----------|------|
| `release_time` | `event_time` (절대 sim 분) |
| `product_name` | `product` |
| `route_name` | `route_id` |
| `lots_count` | `1` |
| `release_interval` | `0` |
| `due_date_sim` | `detail_2.due_date_sim_min` (없으면 release + lead) |
| `wafers_per_lot` | default `1` 또는 master `LotRelease` 매칭 |
| `priority`, `is_super_hot` | default 또는 master |
| `lot_type` | **같은 `lot_id` 재현 시** 엔진이 preferred name으로 사용 (`lot_name_prefix`는 adapter 미연결) |

### 필터

```
event_type == 'ARRIVAL'
AND event_time > T0
AND event_time <= T0 + horizon   (권장)
AND lot_id NOT IN mes_wip_snapshot.lot_id
```

### 주의

| 항목 | 내용 |
|------|------|
| Master vs ARRIVAL | Master = 스케줄 테이블. ARRIVAL = **실제 투입**. 원 run 재현에는 ARRIVAL 우선 |
| `use_master_lot_release=true` | ARRIVAL plan과 **동시 사용 금지** |
| 시각축 | `mes_scenario.t0_sim_minute` = CSV T0와 동일 run·동일 절대축 |

---

## 6. `mes_cqt_snapshot`

**이번 task 제외.** 0행으로 `load_mes_scenario` 후 run 가능.

---

## 7. 산출물·실행 체크리스트

### 구현 산출물

1. `simulation/tools/build_forward_scenario_from_csv.py` — CSV 번들 생성 (`scenario_out/<id>/`)
2. `simulation/tools/promote_scenario_validated.py`
3. `simulation/tools/run_forward_pipeline.sh` — build → load → VALIDATED → run

**로컬 DB (docker `5433`) 예시**

```bash
cd FAB_BEAR/simulation
export DATABASE_URL=postgresql://postgres:postgres@localhost:5433/postgres

chmod +x tools/run_forward_pipeline.sh
./tools/run_forward_pipeline.sh f5178b41645d 620 60 FWD_CSV_f5178_T620 \
  /path/to/sim_csv_kpi_check
```

**T0 주의**: `kpi_tool.snapshot_time`은 보통 60분 격자. T0는 KPI 행이 있는 시각을 쓸 것.

**파이프라인 수동 단계**

1. `build_forward_scenario_from_csv.py` (`build_confidence.json` 참고)
2. `load_mes_scenario.py --create-tables ...`
3. `promote_scenario_validated.py`
4. `run_sim_forward_once.py --scenario-id ...`

### 검증

- [ ] 동일 `run_id`만 사용
- [ ] T0: `tool_state` unit 행 존재
- [ ] `mes_wip` PROCESSING lot마다 `processing_remaining_min > 0`
- [ ] queue lot ⊆ `mes_wip`
- [ ] T0 이전 ARRIVAL ⊄ release plan
- [ ] `use_master_lot_release = false`
- [ ] `validation_report`에 `missing_tools` / `missing_routes` 없음
- [ ] Run 후 `mes_scenario.status = DONE`, `simulation_run` 생성

### 성공 기준 (PoC)

- Runner exit 0, `active_lots remaining`이 원 run T0+H 대비 **대략 동일 order of magnitude**
- KPI/로그가 쌓임 (빈 fab 아님)

---

## 8. 의사결정 요약 (논의 반영)

| 주제 | 결론 |
|------|------|
| 3종 log만으로 4 snapshot **정확 복원** | ❌ |
| 3종 log + KPI + 마스터로 **PoC 채우기** | ✅ |
| `simulation_process.arrive_time` for in-flight | ❌ (완료 후 row만) |
| LOADING → queue | ❌ |
| route step + not RUN on tool → queue | ✅ (dispatch로 unit 확정) |
| `kpi_tool.q_len` @ T0 | queue **개수** SSOT |
| T0 이후 ARRIVAL → release plan | ✅ |
| Master DB + `use_master_lot_release=false` | ✅ 충돌 없음 |
| CQT | 생략 |

---

## 9. 참고 코드·문서

| 문서/코드 | 내용 |
|-----------|------|
| `simulation/run_sim_forward_once.py` | VALIDATED runner |
| `simulation/fab_env.py` | `_apply_scenario_overrides`, inject, `_source_process`, `_lot_process` |
| `simulation/load_mes_scenario.py` | CSV → DB |
| `docs/FORWARD_WHATIF_ENGINE.md` | 시계·mental model |
| `docs/MES_FORWARD_WHATIF_SCHEMA.md` | 테이블 스키마 |
| `docs/REPORT_SIMULATION_KPI.md` | `q_len`, KPI 정의 |

---

## 10. Agent에게 시킬 때 한 줄 지시 (복붙용)

> 동일 `sim_csv_out` run_id와 T0(절대 sim 분)를 기준으로, `docs/PROMPT_FORWARD_T0_FROM_SIM_CSV.md`의 알고리즘으로 `mes_tool_snapshot`, `mes_tool_queue_snapshot`, `mes_wip_snapshot`, `mes_lot_release_plan`, `mes_scenario`(FORWARD, `use_master_lot_release=false`) CSV를 생성하고 `load_mes_scenario.py`로 DB에 넣은 뒤 VALIDATED로 올려 `run_sim_forward_once.py`를 실행하라. CQT는 생략. queue lot은 반드시 wip에도 포함. PROCESSING lot은 `processing_remaining_min`을 마스터 step `proc_time_mean`으로 추정하라. T0 이후 투입은 `lot_events` ARRIVAL만 사용하고 master lot_release spawn은 쓰지 마라.
