# Task: FORWARD / WHAT-IF 시뮬레이션 엔진 구현 (FAB_BEAR)

## 배경

### 결정된 것
- DB 스키마 V2 (`V001 + V002__mes_forward_whatif.sql`) 적용 완료. 자세한 내용: `docs/MES_FORWARD_WHATIF_SCHEMA.md`.
- 모드 정의:
  - **FORWARD**: T0 스냅샷 + `mes_lot_release_plan` + 엔진(`fab_env.py` rule dispatch) → x분 전개.
  - **WHAT-IF**: FORWARD baseline + `mes_whatif_action`(변경분만) → 동일 엔진에 override 주입.
- 출력: 기존 `simulation_run`, `simulation_log`, `lot_event_log`, `tool_state_log`, `kpi_snapshot` + `mes_scenario_run`.

### 결정되지 않은 것 (TBD)
- **Trigger 정의**:
  - FORWARD trigger: ML(XGBoost) + 룰이 “병목 임박” 판단 → T0/scenario 자동 생성? 또는 수동?
  - WHAT-IF trigger: AI Agent가 어떤 신호(KPI delta, due risk, …)로 `mes_whatif_action` 생성하는지 미정.
- Agent action 스펙(payload key/value)이 V002 `mes_whatif_action.action_kind` enum 외 확장 필요한지 미정.

→ **이 task는 trigger 외부**(상위 시스템)에서 “시나리오가 DB에 들어왔다고 가정”하고 **엔진 측 구현**만 한다. Trigger 인터페이스는 명확한 contract만 정의해 추후 ML/Agent 측과 맞춘다.

---

## 기존 코드 참조

| 경로 | 역할 |
|------|------|
| `simulation/fab_env.py` | `FabEnv(gym.Env)` — reset/step, `_build_simulation`, `_source_process`, `_lot_process`, `_dispatch_for_tool`, `_choose_tool_for_lot`, CQT/batch/PM/BD |
| `simulation/run_sim_csv_once.py` | 기존 실행기 (cold start, `SIM_END_MINUTES` 종료) |
| `simulation/models.py` | `MesScenario`, `MesWipSnapshot`, `MesToolSnapshot`, `MesToolQueueSnapshot`, `MesCqtSnapshot`, `MesLotReleasePlan`, `MesForwardInputEvent`, `MesWhatifAction`, `MesOperatingEvent`, `MesScenarioRun` |
| `simulation/load_mes_scenario.py` | CSV → DB ETL + validation |
| `simulation/database.py` | `SessionLocal` |
| `simulation/csv_db_mapping.py` + `load_csv_to_db.py` | 결과 CSV → 로그 테이블 |

**중요 호환 규칙**
- `tool_id` 형식: `{toolgroup_name}#{idx}` (기존 빌더와 동일).
- **시간 (확정 — sim clock offset)**:
  - SimPy `sim_env.now` = **0 ~ horizon** (상대 분).
  - `self._sim_clock_offset = t0_sim_minute` (절대 fab 시각).
  - **엔진/로그/KPI에 기록하는 시각** = `sim_env.now + offset` (= 절대 sim 분, DB `scheduled_time`과 동일 축).
  - Trigger 병목 시점 T0에서 **T0 ~ T0+x** 를 돌리는 것 = SimPy **0 ~ x** 를 돌리는 것과 동일 (스냅샷이 T0 상태이므로 **0부터 시작해도 됨**).
- 기존 `SIM_END_MINUTES`, `SIM_CSV_DIR`, `DISPATCH_MODE` 환경변수는 유지하되 시나리오 모드가 우선.

---

## 구현 범위

### 비목표 (V2 명시)
- Full MES TRACK_IN/OUT replay 재현 (`DISPATCH_MODE=mes_replay` X).
- `predecessor_event_id`.
- 미래 PM/BD 캘린더 deterministic (마스터 stochastic 유지).
- Trigger 자동화 코드 (ML/Agent 측 outside this task).

### 1차 목표 (P0)
1. **`FabEnv.reset(options={"scenario_id": ...})`** — 시나리오 모드별 초기화.
2. **T0 스냅샷 주입**: `mes_wip_snapshot`, `mes_tool_snapshot`, `mes_tool_queue_snapshot`, (선택) `mes_cqt_snapshot`을 FabEnv 메모리(`active_lots_data`, `tools[*].queue`, `tools[*].current_setup`, `active_cqt`)에 복원.
3. **`_sim_clock_offset = t0`**, **`sim_env.now`는 0부터**, **`sim_end_minutes = horizon_minutes`** (상대). 로그/KPI는 `now + offset` 기록.
4. **FORWARD release**: 마스터 `lot_release` 대신 `mes_lot_release_plan`을 `_source_process` 호환 형태로 spawn (또는 `use_master_lot_release=True`면 마스터 `lot_release`를 [t0, t0+x] 필터).
5. **`run_sim_forward_once.py`** — 시나리오 실행기. 끝나면 `simulation_run` + `mes_scenario_run` insert.

### 2차 목표 (P1)
6. **WHAT-IF override 주입**:
   - 시작 시 적용 가능한 action: `LOT_PRIORITY`, `LOT_HOLD`, `DISPATCH_RULE_OVERRIDE`, `FORCE_TOOL`, `SKIP_RELEASE`, `ADD_RELEASE`.
   - 실행 중 `effective_time` 도래 시 적용하는 작은 SimPy process 1개.
   - `payload_json` 스키마는 **시뮬 엔진이 SSOT** (아래 § Locked decisions #4). Agent는 추후 동일 키로 맞춤.
7. **WHAT-IF 결과 비교** — run 종료 후 `kpi_whatif_diff` 테이블에 baseline vs what-if KPI delta 적재 (+ SQL view).

### 선택 (P2)
8. `mes_forward_input_event` (HOLD/RELEASE/FAB_ARRIVAL) 처리.
9. `mes_operating_event` (SCRAP/REWORK) 시간 도래 시 강제 적용.

---

## 상세 설계

### A) `FabEnv` 변경

#### A-1. `reset(seed=None, options=None)`
- `options = options or {}`
- `scenario_id = options.get("scenario_id") or os.environ.get("SIM_SCENARIO_ID")`
- 없으면 기존(cold start) 경로 그대로.
- 있으면:
  1. `MesScenario` 로드 → `mode`, `t0`, `horizon`, `baseline_scenario_id`, `use_master_lot_release` 메모리에 저장.
  2. `_build_simulation(db)` 기존 마스터 로드까지는 동일.
  3. **`_apply_scenario_overrides(db, scenario)`** 신규 호출.
  4. **Sim clock offset (확정)**:
     - `self._sim_clock_offset = float(scenario.t0_sim_minute)`
     - `self._sim_now_abs()` → `self.sim_env.now + self._sim_clock_offset` (로그·KPI·release 비교용)
     - DB 절대 시각 `t_abs` → SimPy delay: `max(0, t_abs - self._sim_clock_offset)`
     - `self.sim_end_minutes = float(scenario.horizon_minutes)` — **상대** 종료 (now >= horizon)
  5. T0~T0+x run = SimPy 0~x run (스냅샷이 T0이므로 상대 0 시작이 맞음).
  6. `mes_scenario.status = 'RUNNING'`, `mes_scenario_run` insert.

#### A-2. `_apply_scenario_overrides(db, scenario)`
1. **신규 helper들**:
   - `_inject_t0_wip(db, scenario)` — `MesWipSnapshot` 순회:
     - `active_lots_data[lot_id] = {...}` 채우기.
     - `issued_lot_names.add(lot_id)`.
     - SimPy process `_lot_process(...)`를 **WIP 진입 step부터** 다시 시작하게 spawn. 큐 위치는 `_inject_t0_queue`에서 구성.
     - `status == PROCESSING`:
       - `processing_remaining_min` **있음** → 해당 툴 점유 + `timeout(remaining)` 후 step 진행.
       - **비어 있음/NULL (확정 fallback)** → 해당 툴을 **비어 있는 장비**로 간주, `remaining=0`, **즉시 FINISH** 처리 후 다음 step/큐로 (ETL 누락 = 버그로 간주하되 엔진은 중단하지 않음).
     - `status == WAIT_BATCH`이면 batch_queues에 push.
   - `_inject_t0_tools(db, scenario)` — `MesToolSnapshot`:
     - `tools[tool_id]["current_setup"]`, `op_state` 설정.
     - `DOWN_PM`/`DOWN_BM` (확정): `MesToolSnapshot.op_state` 복원 + down process spawn (P0 포함).
   - `_inject_t0_queues(db, scenario)` — `MesToolQueueSnapshot` 정렬해서 각 tool의 `queue`에 permission_event payload를 만들어 push.
   - `_inject_t0_cqt(db, scenario)` — `MesCqtSnapshot` → `active_cqt[lot_id] = {...}`.
2. **Release 주입** (`mode == FORWARD` 또는 WHAT-IF):
   - `MesLotReleasePlan` 순회 → 기존 `_source_process(r)` 시그니처를 따르는 어댑터 객체(`LotReleaseLike`)를 만들어 `self.sim_env.process(self._source_process(adapter))`.
   - `use_master_lot_release=True`면 마스터 `LotRelease`를 `[t0, t0+horizon]` 필터.
   - 둘 다 없는 시나리오는 release 없음(WIP만으로 진행).
3. **WHAT-IF action 주입**:
   - `start_actions = [a for a in actions if a.effective_time <= now]` 먼저 즉시 적용.
   - 나머지는 `_whatif_action_loop` SimPy process로 `timeout(action.effective_time - now)` 후 적용.
   - **`_apply_whatif_action(action)`**:
     - `LOT_PRIORITY` → `active_lots_data[lot_id]["priority"] = payload.priority`; 큐 안 permission_event payload도 동기화.
     - `LOT_HOLD` → 해당 lot 큐에서 제외 또는 `hold_lots` set에 추가 → `_dispatch_for_tool`에서 skip.
     - `LOT_RELEASE` → `hold_lots`에서 제거.
     - `DISPATCH_RULE_OVERRIDE` → `self.dispatch_rule_override[tool_group] = payload.dispatch_rule` → `_select_dispatch_candidate`가 우선 사용.
     - `FORCE_TOOL` → `payload`의 `tool_id`, `once` (bool) 반영 (§4). `once=false`면 해당 (lot, route, step) 또는 TG 범위에서 dispatch 시 계속 강제.
     - `SKIP_RELEASE` → release id를 set에 넣어 `_source_process`에서 spawn 직전 skip.
     - `ADD_RELEASE` → 새 release adapter 즉시 spawn.

#### A-3. `_dispatch_for_tool` / `_select_dispatch_candidate` 보강
- 시작에서 `dispatch_rule_override`가 있으면 그 rule 사용.
- `hold_lots` 안 lot은 dispatch candidate에서 제외.
- `force_next_tool`이 해당 lot에 걸려 있으면 그 tool로 강제 큐 인서트 (이미 큐에 있으면 우선순위 1로 변경).

#### A-4. 결과 기록
- 기존 CSV/DB 로그 그대로.
- `step()` 종료 조건은 기존 그대로 `sim_env.now >= sim_end_minutes`.
- Run 종료 시 (어디서 호출하든) `mes_scenario_run.finished_at`, `validation_report` 업데이트.

### B) `run_sim_forward_once.py`
- Usage:
  ```bash
  .venv/bin/python run_sim_forward_once.py --scenario-id FWD_DEMO_180 [--csv-dir ./sim_csv_out]
  ```
- 흐름:
  1. `MesScenario` 로드, 시나리오 모드/t0/horizon 출력.
  2. `os.environ["SIM_SCENARIO_ID"] = scenario_id`.
  3. `env = FabEnv(); env.reset(options={"scenario_id": ...})`.
  4. 기존 `run_sim_csv_once.py` step loop 패턴 그대로 (rule dispatch).
  5. 종료 후:
     - `mes_scenario.status='DONE'`.
     - `mes_scenario_run` row 마무리 (이미 reset 시 생성).
     - 요약 print (release 수, finished lots, KPI summary).

### C) WHAT-IF 비교 (P1)
- 같은 runner 사용 (`--scenario-id WHATIF_DEMO_180`).
- Run 종료 후 `tools/compare_whatif.py` (또는 runner 내장):
  - `baseline_scenario_id` / `v_mes_scenario_run_pair`로 FORWARD `run_id` vs WHAT-IF `run_id` 조회.
  - `kpi_snapshot` join → **`kpi_whatif_diff`** insert (MES 입력 테이블과 별도, **시뮬 출력 전용**).

### D) `kpi_whatif_diff` 테이블 (확정, V003 migration)

| 컬럼 | 설명 |
|------|------|
| `id` | PK |
| `whatif_scenario_id` | FK |
| `baseline_run_id`, `whatif_run_id` | FK `simulation_run` |
| `level`, `scope`, `kpi_name` | `kpi_snapshot`과 동형 |
| `baseline_value`, `whatif_value`, `delta` | |
| `snapshot_time` | 절대 sim 분 (offset 적용 후) |
| `computed_at` | timestamptz |

**용도:** Agent/리포트용 “대응 전후 KPI 차이”. MES cron 스케줄 데이터가 아님.

---

## Trigger 인터페이스 (외부, contract만)

엔진은 trigger를 모르고, DB에 들어온 시나리오만 실행한다. 다른 시스템과의 합의 사항을 문서로 남긴다.

| Trigger | 책임 | 결과물 |
|---------|------|--------|
| **FORWARD trigger** (ML+rule, TBD) | 병목 임박 판정 | `mes_scenario` (mode=FORWARD) + WIP/Tool 스냅샷 + release plan 생성 |
| **WHAT-IF trigger** (AI Agent, TBD) | 대응안 생성 | `mes_scenario` (mode=WHATIF, baseline=...) + `mes_whatif_action` rows |

엔진 측 “계약(contract)”:
- **status (확정):** ETL(`load_mes_scenario.py`)은 **`DRAFT`만** 설정. **`VALIDATED`는 Trigger(ML/Agent/운영)가 명시 승격** 후에만 `run_sim_forward_once.py`가 실행 가능 (`status != VALIDATED` → exit 1).
- 엔진은 `VALIDATED` → `RUNNING` → `DONE` 책임.
- **동일 시나리오 재실행 (확정):** 결과 `simulation_run` / `mes_scenario_run` / `kpi_*` **누적** (새 `run_id` per run).
- `trigger_meta` JSON 키 (TBD, 예시): `{"source": "ml|agent", "model": "...", "trigger_time_sim": float, "bottleneck_tg": "...", ...}`.

이번 task에서는 contract만 문서로 남기고, trigger 코드는 작성하지 않는다.

---

## 산출물

1. `simulation/fab_env.py` 패치:
   - `reset(options={"scenario_id": ...})`
   - `_apply_scenario_overrides` + 4개 inject helper
   - `_whatif_action_loop` + `_apply_whatif_action`
   - dispatch override hooks
   - sim clock offset (또는 t0-relative 변환)
2. `simulation/run_sim_forward_once.py` 신규 (기존 `run_sim_csv_once.py` 참고).
3. `simulation/core/scenario_loader.py` (선택) — DB → in-memory dataclass 변환.
4. `tests/test_scenario_forward_smoke.py` — 작은 시나리오 1개 reset → 1 step → exception 없이 종료.
5. `docs/FORWARD_WHATIF_ENGINE.md` — 구현/사용 가이드 (env vars, CLI, hook 그림).
6. `docs/TRIGGER_CONTRACT.md` — trigger contract (VALIDATED 승격, trigger_meta).
7. `sql/flyway/V003__kpi_whatif_diff.sql` + `models.KpiWhatifDiff`.
8. `load_mes_scenario.py` 수정: 종료 시 **`status=DRAFT` 유지** (자동 VALIDATED 제거).

---

## 검증 체크리스트

| 항목 | 기대 |
|------|------|
| `mode=FORWARD` 시 master `lot_release`로 release 안 함 | release count == `mes_lot_release_plan` 합 |
| `sim_env.now`는 0부터, `_sim_now_abs()`는 t0부터 | True |
| `run_sim_forward_once`는 `status=VALIDATED`만 허용 | True |
| WHAT-IF 종료 후 `kpi_whatif_diff` rows | ≥1 (baseline+whatif run 존재 시) |
| WIP lot이 `simulation_log`/`lot_event_log`에 ARRIVAL부터 다시 안 적혀야 함 (이미 진행 중) | OK |
| WHAT-IF `LOT_PRIORITY` 이후 같은 lot의 dispatch 순위 상승 | OK |
| `mes_scenario.status` 전이: VALIDATED → RUNNING → DONE | OK |
| `mes_scenario_run` row 한 시나리오당 1+ (재실행 시 누적) | OK |
| KPI snapshot 출력은 `t0 + 60, 120, 180, ...` | OK |
| 시나리오 없는 cold start (`scenario_id` 미지정) 기존 동작 회귀 X | OK |

---

## Locked decisions (확정 — 구현 시 따를 것)

### 1. Sim clock offset

- **확정:** `offset = t0_sim_minute`, SimPy **0 ~ horizon** 실행.
- **T0에서 T0+x 시뮬** = 스냅샷(T0 상태) + **상대 0~x분** 전개. **SimPy를 0부터 시작해도 됨** (offset으로 로그/KPI/release는 절대 시각 T0~T0+x와 일치).
- 구현 헬퍼: `_sim_now_abs()`, `_timeout_until_abs(t_abs)`.

### 2. `PROCESSING` WIP — `processing_remaining_min`

- ETL 정상: **반드시 채움** (진행 중 공정 종료 시각을 알아야 함).
- **NULL/누락 시 (확정 fallback):** 해당 툴 **비어 있음** 가정 → `remaining=0` → **즉시 FINISH** (엔진 크래시 X, validation warning 권장).

### 3. `DOWN_PM` / `DOWN_BM` tool 스냅샷

- **확정:** P0에서 `mes_tool_snapshot.op_state` 복원 지원.

### 4. `mes_whatif_action.payload_json` — **엔진 SSOT**

Agent/ETL은 미설계 → **FabEnv 파서가 기준**. Agent는 이 스키마에 맞춤.

| `action_kind` | `payload_json` (required keys) | 엔진 동작 |
|---------------|----------------------------------|-----------|
| `LOT_PRIORITY` | `{"priority": int}` | Lot/큐 payload priority 갱신 |
| `LOT_HOLD` | `{}` 또는 `{"reason": str}` | `hold_lots` 추가, dispatch 제외 |
| `LOT_RELEASE` | `{}` | `hold_lots` 제거 |
| `DISPATCH_RULE_OVERRIDE` | `{"tool_group": str, "dispatch_rule": str}` | TG rule override |
| `FORCE_TOOL` | `{"tool_id": str, "once": bool, "tool_group": str?}` | 지정 툴#로 dispatch 강제; `once` 선택 가능 (§5) |
| `SKIP_RELEASE` | `{"mes_lot_release_plan_id": int}` | 해당 release spawn skip |
| `ADD_RELEASE` | `{"product_name", "route_name", "release_time", "lots_count", ...}` | 즉시 release spawn |

- JSON 키 이름 **변경 금지** (Agent 호환).

### 5. `FORCE_TOOL` — `once: true | false` (선택 가능)

| `once` | 용도 | 모드 |
|--------|------|------|
| **`false` (기본)** | 해당 조건에서 **계속** 그 `tool_id`로 dispatch (같은 TG 내 다른 장비로 옮기기, 다음 step도 지정 툴 등 WHAT-IF) | **WHAT-IF** |
| **`true`** | **다음 1회** dispatch만 강제, 이후 `route_id`/dispatch rule 정상 | WHAT-IF (일시 조치) |
| *(미사용)* | FORWARD는 `FORCE_TOOL` action 없음 → 항상 rule dispatch (`once` 무관) | **FORWARD** |

- `lot_id` + `route_id` + `step_seq` (+ `tool_group`)로 적용 범위 한정.
- 예 (WHAT-IF): “같은 Litho_FE인데 **#2로만** 보내라” → `{"tool_group":"Litho_FE","tool_id":"Litho_FE#2","once":false}`.

### 6. WHAT-IF KPI diff 테이블

- **확정:** `kpi_whatif_diff` (시뮬 **출력**, MES cron 입력 아님).
- WHAT-IF run 종료 시 baseline run과 join해 delta 적재.

### 7. 재실행 정책

- **확정:** 동일 `scenario_id` 여러 run → `simulation_run` / `mes_scenario_run` / KPI **누적** (run_id UUID per execution).

### 8. 시나리오 `status` 승격

- **확정:** `load_mes_scenario.py` → **`DRAFT`만** (validation 통과해도 VALIDATED 자동 승격 **안 함**).
- **Trigger(ML/Agent/운영)** → 검토 후 `UPDATE mes_scenario SET status='VALIDATED'`.
- `run_sim_forward_once.py` → `status == 'VALIDATED'` 아니면 거부.

---

## Remaining TBD (이 프롬프트 밖 — Trigger만)

| 항목 | 상태 |
|------|------|
| FORWARD trigger (ML+rule)가 scenario/스냅샷을 **어떻게 생성**하는지 | TBD |
| WHAT-IF trigger (Agent)가 **어떤 신호**로 action 생성하는지 | TBD |
| `trigger_meta` 필수 필드 목록 | TBD (예시만) |

---

## 비목표 명시 (다시)

- ML/Agent trigger 코드 (다른 task)
- `mes_schedule_event` TRACK_IN replay
- 기존 결과 로그 테이블 **컬럼 변경** (`kpi_whatif_diff` **추가**는 OK)

---

Please output:
1. `fab_env.py` 패치 (offset, scenario reset, inject, what-if, `_sim_now_abs`)
2. `run_sim_forward_once.py` (`VALIDATED` only)
3. `core/scenario_loader.py` (선택)
4. `sql/flyway/V003__kpi_whatif_diff.sql` + `models.KpiWhatifDiff`
5. `tools/compare_whatif.py` → fill `kpi_whatif_diff`
6. `load_mes_scenario.py` — remove auto-VALIDATED; keep DRAFT
7. pytest smoke test 1개
8. `docs/FORWARD_WHATIF_ENGINE.md`, `docs/TRIGGER_CONTRACT.md`

**Do not re-open Locked decisions §1–8 unless product owner changes them.**
