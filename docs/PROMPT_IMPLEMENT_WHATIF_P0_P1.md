# Task: WHAT-IF PoC — P0 (scenario + compare) + P1 (engine actions)

## 목적

Schedule replay **없이**, 회의 합의대로:

- **FORWARD (baseline):** T0 snapshot + rule dispatch + `mes_lot_release_plan` → H분 전개 → KPI
- **WHAT-IF:** 동일 T0 snapshot + **생산 계획 diff** + **`mes_whatif_action`** → H분 → baseline 대비 KPI diff

**범위:** P0 + P1만. P2(CR-first dispatch, `MODIFY_RELEASE` 고도화)는 제외.

**비목표:** `DISPATCH_MODE=schedule_replay`, `mes_schedule_event`, bit-identical ref run 재현.

---

## FORCE_TOOL vs REQUEUE_TOOL (Locked decision)

| | `FORCE_TOOL` | `REQUEUE_TOOL` (P1 신규) |
|---|--------------|-------------------------|
| **용도** | Lot이 **다음** TG 진입 시 #Tool pin; **이미 그 tool queue**에 있으면 dispatch 우선 | Lot이 **현재 step**에서 **다른 #Tool queue**로 이동 |
| **queue 간 이동** | 없음 | 있음 |
| **P0/P1** | **유지** (제거하지 않음) | **신규 구현** |

**Agent 가이드 (문서에 명시):**

- 이미 tool A queue에 잘못 대기 → **`REQUEUE_TOOL`**
- 아직 queue 없음 / 다음 step에서 특정 unit 고정 → **`FORCE_TOOL`** (`once: true` 권장)

나중에 필요한가? **예.** 부하 분산(재배치)은 REQUEUE, 예약/다음 방문 고정은 FORCE_TOOL이 더 가볍다.

---

## Phase P0 — 데이터 + 실행 + KPI 비교 (엔진 신규 kind 없음)

### P0.1 시나리오 2종

| 시나리오 | `mode` | `baseline_scenario_id` | snapshot | release plan |
|----------|--------|------------------------|----------|--------------|
| `FWD_BASE_<tag>` | `FORWARD` | `NULL` | 동일 T0 4종 | **baseline** `mes_lot_release_plan.csv` |
| `FWD_WHATIF_<tag>` | `WHATIF` | `FWD_BASE_<tag>` | **동일** (wip/tool/queue/cqt) | **what-if** plan (diff) |

공통 메타 예:

- `t0_sim_minute` = T0 (절대 fab 분)
- `horizon_minutes` = 120 (2h) — 운영 합의값
- `use_master_lot_release` = **false**
- ETL 후 `status` = `DRAFT` → 검증 후 **`VALIDATED`**

### P0.2 생산 계획 diff (`mes_lot_release_plan`) — 엔진 변경 없음

baseline vs what-if CSV에서 아래 컬럼만 다르게 (예시):

| 컬럼 | baseline | what-if (예) |
|------|----------|--------------|
| `release_time` | 원본 | 일부 lot 지연 (`> T0`) |
| `priority` | 원본 | 급한 product ↑ |
| `release_interval` | 원본 | 간격 축소/확대 |
| `due_date_sim` | 원본 | 조정 |
| `lots_count` | 원본 | 동일 또는 감소 |

**T0 WIP** priority/due/superhot은 **`mes_wip_snapshot.csv` diff** (plan 아님).

### P0.3 `mes_whatif_action` — P0에서 쓸 6 kind (이미 엔진 지원)

`effective_time` = **T0 절대 sim 분** (또는 T0+ε). `seq` = 0,1,…

| seq | `action_kind` | `lot_id` | `tool_group` | `payload_json` |
|-----|---------------|----------|--------------|----------------|
| 0 | `LOT_HOLD` | upstream lot id | — | `{"reason":"relieve_bottleneck"}` |
| 1 | `LOT_PRIORITY` | urgent lot id | — | `{"priority":99}` |
| 2 | `DISPATCH_RULE_OVERRIDE` | — | bottleneck TG | `{"tool_group":"<TG>","dispatch_rule":"superhotlot setupavoidance"}` |
| 3 | `SKIP_RELEASE` | — | — | `{"mes_lot_release_plan_id":<plan_row_id>}` |
| 4 | `FORCE_TOOL` | lot id | TG | `{"tool_id":"<TG>#k","tool_group":"<TG>","once":true}` |
| 5 | `LOT_RELEASE` | (held lot) | — | `{}` — optional, `effective_time` = T0+30 |

CSV: `mes_whatif_action.csv` — `load_mes_scenario.py`가 적재 (`MesWhatifAction`).

### P0.4 실행

```bash
cd FAB_BEAR/simulation
.venv/bin/python load_mes_scenario.py --scenario-dir scenario_out/FWD_BASE_<tag>/ ...
# promote VALIDATED
.venv/bin/python run_sim_forward_once.py --scenario-id FWD_BASE_<tag> --csv-dir sim_csv_out/base_<tag>

.venv/bin/python load_mes_scenario.py --scenario-dir scenario_out/FWD_WHATIF_<tag>/ ...
.venv/bin/python run_sim_forward_once.py --scenario-id FWD_WHATIF_<tag> --csv-dir sim_csv_out/whatif_<tag>
```

### P0.5 KPI compare

**목표:** `@ snapshot_time ≈ T0 + H` (또는 구간) FAB/TG KPI delta.

구현 옵션 (하나 선택, P0 acceptance에 포함):

1. **`tools/compare_whatif.py`** (없으면 신규): baseline run_id vs what-if run_id → `kpi_whatif_diff` 채우기 또는 summary CSV
2. **최소:** `kpi_toolgroup.csv` / `kpi_fab.csv`에서 `snapshot_time = T0+H` 행 diff 스크립트

비교 KPI 예: `q_len`, `processing_count`, `utilization` (TG scope), fab WIP.

### P0 산출물

- [ ] `scenario_out/FWD_BASE_*` / `FWD_WHATIF_*` CSV 번들 + load OK
- [ ] 두 run `DONE`, `lot_release_ledger` / `kpi_*` 생성
- [ ] compare 산출물 1종 (table 또는 CSV)
- [ ] `docs/MES_WHATIF_ACTION.md` 초안 (P0 kinds + payload 표)

---

## Phase P1 — 엔진 + 테스트 + 문서

### P1.1 `SET_SUPER_HOT` (신규 `action_kind`)

**동작:** `LOT_PRIORITY`와 동일 패턴.

- `payload_json`: `{"super_hot": true}` 또는 `false`
- `lot_id` 필수
- `active_lots_data` + 모든 tool `queue` payload `super_hot` 갱신

**파일:** `fab_env.py` → `_apply_whatif_action`

**테스트:** queue에 lot 넣은 뒤 action 적용 → `_select_dispatch_candidate`가 superhot 필터 타는지.

### P1.2 `REQUEUE_TOOL` (신규 `action_kind`)

**동작:** lot이 **현재** 특정 TG의 한 tool queue에 대기 중일 때, **다른 candidate #Tool** queue로 이동 (동일 step).

**payload_json (SSOT):**

```json
{
  "tool_group": "Litho_FE_111",
  "from_tool_id": "Litho_FE_111#1",
  "to_tool_id": "Litho_FE_111#7",
  "step_seq": 159
}
```

| 필드 | 필수 | 설명 |
|------|------|------|
| `tool_group` | Y | TG 이름 |
| `to_tool_id` | Y | 이동 대상 #Tool |
| `from_tool_id` | N | 없으면 TG 내 lot이 있는 첫 queue 검색 |
| `step_seq` | N | 검증용; payload `step_seq`와 불일치 시 report warning |

**알고리즘 (권장):**

1. `lot_id`로 `tools[*].queue` + `batch_queues` (해당 tool 키) 스캔
2. 매칭 `simpy` event 제거 (queue list에서 pop)
3. `to_tool_id` queue에 재 append: **기존 payload 유지**, `enqueue_time = sim_env.now` (또는 유지 — 문서화)
4. `_check_trigger(to_tool_id)` 호출
5. lot이 **PROCESSING** 중이면 REQUEUE **거부** (validation report)

**파일:** `fab_env.py` — `_apply_whatif_action`, helper `_requeue_lot_tool(...)`

**테스트:** 2-tool TG, lot on #1 queue → REQUEUE → #7 only.

### P1.3 `MODIFY_RELEASE` (선택 — P1에 시간 있으면)

**동작:** 아직 spawn 안 된 `MesLotReleasePlan` 행을 SimPy 시작 전에 패치.

- `payload`: `mes_lot_release_plan_id`, optional `priority`, `due_date_sim`, `release_time`
- `_spawn_lot_release_plan` **전** in-memory patch 또는 DB reload

**없어도 P1 완료 가능** — P0 plan CSV diff로 대체.

### P1.4 `FORCE_TOOL` — 변경 없음

- 삭제·deprecated 하지 않음
- `MES_WHATIF_ACTION.md`에 REQUEUE vs FORCE 선택 가이드만 추가

### P1.5 문서 `docs/MES_WHATIF_ACTION.md`

포함:

- 전체 `action_kind` 표 (기존 7 + SET_SUPER_HOT + REQUEUE_TOOL [+ MODIFY_RELEASE])
- payload JSON 스키마
- `effective_time` 규칙 (절대 fab 분)
- baseline / WHAT-IF 시나리오 구성
- Agent: T0 CR → `LOT_PRIORITY` / `SET_SUPER_HOT` / `REQUEUE` / plan diff
- P0 예시 6행 + P1 예시 2행

### P1.6 테스트

| 파일 | 내용 |
|------|------|
| `tests/test_whatif_set_super_hot.py` | 신규 |
| `tests/test_whatif_requeue_tool.py` | 신규 |
| `tests/test_scenario_forward_smoke.py` | 회귀 |
| `tests/test_lot_release_ledger.py` | 회귀 |

---

## 파일 touch list

| Phase | 파일 |
|-------|------|
| P0 | `scenario_out/**` 샘플, `load_mes_scenario.py` (변경 없거나 CSV 검증만), `run_sim_forward_once.py`, `tools/compare_whatif.py` (신규 권장) |
| P1 | `fab_env.py`, `docs/MES_WHATIF_ACTION.md`, `tests/test_whatif_*.py` |
| 정리 | `REPORT_SCHEDULE_REPLAY.md` 상단 “superseded by policy WHAT-IF” 1문단 (선택) |

---

## Acceptance checklist

### P0

- [ ] `FWD_BASE_*` / `FWD_WHATIF_*` VALIDATED, 동일 T0 snapshot
- [ ] `mes_lot_release_plan` diff only on what-if (또는 wip diff 명시)
- [ ] what-if에 `mes_whatif_action` ≥ 4행 (HOLD, PRIORITY, SKIP or ADD, DISPATCH or FORCE)
- [ ] 두 run 완료, KPI @ T0+H 비교 산출

### P1

- [ ] `SET_SUPER_HOT` 적용 시 queue dispatch superhot 반영
- [ ] `REQUEUE_TOOL` cross-tool queue 이동 + trigger
- [ ] `FORCE_TOOL` 기존 테스트 통과
- [ ] `MES_WHATIF_ACTION.md` 완료
- [ ] pytest green

---

## 구현 순서

1. P0 sample `scenario_out` + load + 2× `run_sim_forward_once`
2. `compare_whatif` (또는 KPI diff script)
3. P1 `SET_SUPER_HOT` + tests
4. P1 `REQUEUE_TOOL` + tests
5. (optional) `MODIFY_RELEASE`
6. 문서 + `REPORT_SCHEDULE_REPLAY` deprecate note

---

## Agent integration (참고, 본 task 범위外)

1. T0 병목 TG 식별 (KPI/ML)
2. CR from `lot_release_ledger` ⋈ `mes_wip_snapshot`
3. Emit `mes_whatif_action.csv` + optional plan/wip diff CSV
4. Trigger: load → VALIDATED → run → compare

EOF
