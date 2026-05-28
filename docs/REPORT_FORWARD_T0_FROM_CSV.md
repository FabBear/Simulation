# FORWARD T0 시나리오 CSV 역추정 — 기술 보고서

| 항목 | 내용 |
|------|------|
| 문서 번호 | FAB_BEAR-REP-FWD-CSV-001 |
| 프로젝트 | FabGuard PoC — FORWARD 시뮬레이션 입력 구축 |
| 관련 문서 | [PROMPT_FORWARD_T0_FROM_SIM_CSV.md](./PROMPT_FORWARD_T0_FROM_SIM_CSV.md), [FORWARD_WHATIF_ENGINE.md](./FORWARD_WHATIF_ENGINE.md) |
| SSOT 코드 | `simulation/tools/build_forward_scenario_from_csv.py`, `load_mes_scenario.py`, `run_sim_forward_once.py` |
| 작성 기준일 | 2026-05-26 |

---

## 1. Executive Summary

FabGuard FORWARD 시뮬레이션(`run_sim_forward_once.py`)은 **DB의 `mes_*` 테이블**을 입력으로 사용한다. Cold-start 실행 결과(`sim_csv_out`의 raw log 3종 + KPI)만으로 **T0 시점 fab 상태**와 **T0 이후 lot 투입 계획**을 역추정해 시나리오를 만들 수 있음을 PoC로 검증했다.

| 구분 | 현재 (PoC) | 향후 (서비스 / AI Agent) |
|------|------------|---------------------------|
| 산출 형태 | `scenario_out/<scenario_id>/*.csv` | 동일 로직 → **Postgres `mes_*` 직접 INSERT/UPSERT** |
| 실행 | `load_mes_scenario.py` → `VALIDATED` → runner | Agent Trigger가 DB 적재 + status 승격 |
| 품질 | 원 run과 **대략 동일** 궤적 (추정·오차 포함) | T0 메모리 export 또는 MES 연동 시 정합 강화 |

**핵심 결론**

1. **3종 Snapshot + `mes_lot_release_plan`** 으로 FORWARD runner 실행 가능 (CQT는 0행 OK).
2. **`mes_lot_release_plan`은 master `LotRelease` 전체가 아니라**, 시나리오 **`horizon` 구간 `(T0, T0+H]`에 실제 fab에 들어오는 lot**을 반영한다 (`lot_events` `ARRIVAL` 기준).
3. CSV는 **중간 산출물·검토용**이며, 서비스화 시 **동일 필드 매핑을 DB API/ETL로 옮기면 된다**.

---

## 2. 배경 및 목적

### 2.1 문제

- `sim_csv_out`은 시뮬 **결과** 로그이지, FORWARD 입력용 `mes_wip_snapshot` 등과 1:1 대응하지 않는다.
- Trigger(ML/Agent)가 병목 시점 **T0**를 고르면, “아무 것도 안 하고 H분 전개”를 돌리려면 **T0 상태 + T0~T0+H 투입**이 DB에 필요하다.

### 2.2 목표

| 입력 | 역할 |
|------|------|
| `mes_tool_snapshot` | T0 장비 `op_state`, setup |
| `mes_tool_queue_snapshot` | tool별 queue (lot, position) |
| `mes_wip_snapshot` | fab 내 lot, step, PROCESSING 잔여 등 |
| `mes_lot_release_plan` | **T0 이후 H분 동안** 새로 들어올 lot |
| `mes_scenario` | `t0_sim_minute`, `horizon_minutes`, `mode=FORWARD`, `use_master_lot_release=false` |

### 2.3 비목표

- 원 cold-start run과 bit-identical 재현
- `mes_cqt_snapshot` (본 PoC에서 제외)
- WHAT-IF `mes_whatif_action` 자동 생성

---

## 3. 아키텍처: CSV PoC → DB 서비스 → AI Agent

```mermaid
flowchart LR
  subgraph today [현재 PoC]
    LOGS["sim_csv_out\nlot_events / tool_state / kpi_tool"]
    BUILD["build_forward_scenario_from_csv.py"]
    CSV["scenario_out/*.csv"]
    LOAD["load_mes_scenario.py"]
    DB[("Postgres mes_*")]
    RUN["run_sim_forward_once.py"]
    LOGS --> BUILD --> CSV --> LOAD --> DB --> RUN
  end

  subgraph future [향후 Agent 서비스]
    TRIGGER["ML/Agent\nT0 + horizon 결정"]
    BUILD2["동일 역추정 로직\n(서버 모듈)"]
    API["MES Scenario API\nDB UPSERT"]
    DB2[("Postgres mes_*")]
    RUN2["Forward runner / K8s Job"]
    TRIGGER --> BUILD2 --> API --> DB2 --> RUN2
  end
```

### 3.1 CSV vs DB

| 관점 | CSV (지금) | DB (서비스) |
|------|------------|-------------|
| 목적 | 사람·Agent가 **검토·diff**하기 쉬움 | `FabEnv.reset(scenario_id=…)` **실행 SSOT** |
| 적재 | `load_mes_scenario.py --wip … --releases …` | 동일 스키마로 INSERT (CSV 생략 가능) |
| 검증 | `validate_scenario()` | 동일 규칙 + status `DRAFT` → `VALIDATED` |
| Runner | CSV **미사용** (DB만 읽음) | 동일 |

**정리:** 지금 CSV로 “보기 좋게” 뽑는 것은 **표현 계층**이다. Agent가 서비스화되면 **같은 필드를 DB에 쓰면** runner 계약은 변하지 않는다.

### 3.2 Agent Trigger 계약 (요약)

1. 병목/이벤트 시 **T0**, **H(horizon)** 결정  
2. 동일 `run_id`의 log + KPI @ T0로 역추정  
3. `mes_scenario` + snapshot 3종 + release plan 적재  
4. Operator/Agent가 **`VALIDATED`** 승격  
5. `run_sim_forward_once.py` (또는 배치 Job) 실행  

상세: [TRIGGER_CONTRACT.md](./TRIGGER_CONTRACT.md)

---

## 4. 데이터 역추정 규칙 요약

### 4.1 입력 SSOT

| 소스 | 용도 |
|------|------|
| `lot_events.csv` | ARRIVAL / LOADING / FINISH, due_date (`detail_2`) |
| `tool_state.csv` | T0 직전 unit별 `op_state`, setup, RUN lot |
| `kpi_tool.csv` @ `snapshot_time=T0` | `q_len`, `processing_count` |
| Postgres 마스터 | `ProcessStep`, ToolGroup, transport, `LotRelease` **참조값** |

**공통:** 동일 `run_id`, 시각은 **절대 sim 분**.

### 4.2 Snapshot별 정확도

| 테이블 | 신뢰도 | 비고 |
|--------|--------|------|
| `mes_tool_snapshot` | 높음 | `tool_state` 마지막 unit 행 |
| `mes_wip_snapshot` | 중~높음 | lot/step/due; `processing_remaining_min`은 **추정** |
| `mes_tool_queue_snapshot` | 중간 | `q_len` + dispatch 휴리스틱; batch 대기는 약함 |
| `mes_lot_release_plan` | 높음 (투입 시각) | ARRIVAL 1건 = plan 1행 |

### 4.3 `mes_lot_release_plan`과 horizon

FORWARD에서 **master `LotRelease`는 spawn하지 않는다** (`use_master_lot_release=false`).

| 항목 | 정의 |
|------|------|
| **포함** | `lot_events`에서 `event_type=ARRIVAL` 이고 **`T0 < event_time ≤ T0 + horizon`** 인 lot |
| **제외** | T0 WIP에 이미 있는 lot (`ARRIVAL ≤ T0`) |
| **1행** | `release_time=event_time`, `lots_count=1`, `due_date_sim` ← ARRIVAL `detail_2` |
| **lot_id 재현** | `lot_type` = CSV `lot_id` (엔진 preferred name) |
| **master DB** | `wafers_per_lot`, `priority` 등 **기본값 보조**만 (자동 투입 X) |

즉 **`mes_lot_release_plan` = “이 FORWARD 구간 H분 동안 fab에 새로 들어올 lot 스케줄”** 이지, 엑셀 master 전체 release 테이블 복사가 아니다.

**예 (검증 시나리오 `FWD_CSV_f5178_T620`, T0=620, H=60)**

- release 4건: `release_time` ∈ (620, 680] — 예: 620.28, 671.97 분  
- `load_mes_scenario.validate_scenario`: `release_time ∈ [T0, T0+H]` 검증 통과  

운영 시 Agent가 **H=180, 1440** 등으로 horizon을 넓히면, plan 행 수는 **그 구간 ARRIVAL 수**에 비례해 늘어난다.

### 4.4 `processing_remaining_min` (PROCESSING WIP)

- 마스터 **현재 step** `proc_time_mean` + transport mean  
- `LOADING` 시각·load/setup 구간 경과로 **잔여 분 추정**  
- 없거나 ≤0이면 엔진이 T0에서 step **즉시 FINISH** (§2 locked)

---

## 5. 검증 수행 내역

PoC 단계에서 **두 차례** 검증을 수행했다. 목적과 깊이가 다르다.

### 5.1 검증 ① — 빌드·파라미터 스MOKE (T0=660, H=180)

| 항목 | 값 |
|------|-----|
| `run_id` | `f5178b41645d` |
| 데이터 | `Simulation/.../sim_csv_kpi_check/` |
| 시나리오 ID | `FWD_CSV_f5178_T660` |
| 결과 | CSV 번들 생성, `build_confidence.json` 기록 |

**산출:** wip 49, releases 6, tools 1535 (KPI @660 전 tool scope), queue 0 ( `q_len=0` trim 이슈 확인)

**학습:** T0는 **KPI `snapshot_time` 격자(60분)** 에 맞출 것; `q_len=0`일 때 queue 후보 trim 로직 보완 필요 → 이후 빌더 수정.

### 5.2 검증 ② — End-to-End 파이프라인 (T0=620, H=60)

| 단계 | 결과 |
|------|------|
| `build_forward_scenario_from_csv.py` | OK — tools 52, queues 39, wip 47, releases 4 |
| `load_mes_scenario.py --create-tables` | OK — Validation OK |
| `promote_scenario_validated.py` | OK |
| **`run_sim_forward_once.py`** | **OK** — exit 0 |

**실행 결과 (요약)**

| 지표 | 값 |
|------|-----|
| `sim_now_rel` | 60.0 (= horizon) |
| `sim_now_abs` | 680.0 (= T0 + H) |
| 시나리오 status | VALIDATED → RUNNING → **DONE** |
| Forward `run_id` | `2bcfff0a6547` |
| Release count (scenario) | 51 |
| Active lots at horizon | 51 |

**번들 경로:** `simulation/scenario_out/FWD_CSV_f5178_T620/`

**부가 수정 (E2E unblock):**

- `database.py`: `expire_on_commit=False` (PM SimPy 프로세스 ORM detached 오류)
- `fab_env.py`: scenario inject 후 `db.expunge_all()`

---

## 6. 한계 및 운영 시 주의

| 항목 | PoC 한계 | 운영 권장 |
|------|----------|-----------|
| T0 정합 | log 역추정 오차 | critical 시 FabEnv T0 export |
| queue 멤버/순서 | dispatch 재현 오차 | KPI `q_len` + 동일 run_id 필수 |
| `processing_remaining_min` | mean 기반 추정 | PROCESSING lot 필수 검증 |
| `kpi_tool` 크기 | long run 5GB+ | `run_id`+`snapshot_time` 스트리밍 필터 |
| DB URL | repo `.env`의 `@db` 호스트 | 로컬: `localhost:5433` 명시 |
| Master release | DB에 있어도 **spawn 안 함** | plan만 horizon 구간 반영 |

---

## 7. 서비스화 로드맵 (제안)

| 단계 | 내용 |
|------|------|
| **P0 (완료)** | `build_forward_scenario_from_csv.py`, CSV 번들, `run_forward_pipeline.sh`, E2E 1회 |
| **P1** | REST/MCP: `(run_id, t0, horizon) → mes_* UPSERT`, `build_confidence` JSON 반환 |
| **P2** | Agent Trigger: 병목 KPI → T0/H 자동 선택, VALIDATED 승격 정책 |
| **P3** | WHAT-IF: baseline scenario + `mes_whatif_action` |
| **P4** | T0 정합 강화: sim 중 checkpoint export 또는 MES feed |

---

## 8. 실행 참고 (재현)

```bash
cd FAB_BEAR/simulation
export DATABASE_URL=postgresql://postgres:postgres@localhost:5433/postgres

./tools/run_forward_pipeline.sh \
  f5178b41645d 620 60 FWD_CSV_f5178_T620 \
  /path/to/sim_csv_kpi_check
```

장기 run (`sim_csv_out`, run `3e11c2ef42da` 등)도 **동일 파이프라인**; T0는 KPI 격자에 맞추고 `kpi_tool.csv`는 스트리밍 처리.

---

## 9. 결론

1. **두 번의 검증**을 수행했다: ① T0=660 빌드 스MOKE, ② **T0=620 full pipeline + forward runner 성공**.  
2. **현재 CSV 출력**은 검토·버전관리용이며, **서비스/Agent 단계에서는 동일 스키마를 DB에 적재**하면 된다. Runner는 처음부터 DB만 본다.  
3. **`mes_lot_release_plan`은 horizon `(T0, T0+H]` 구간의 실제 ARRIVAL(신규 투입)** 을 담는다. Master `LotRelease`는 DB 참조용이며 FORWARD spawn 소스가 아니다.  
4. PoC 품질로 “같은 run 궤적을 대략 이어가기”는 가능; production 정합이 필요하면 T0 export 또는 MES 연동을 병행한다.

---

## 부록 A. 생성 파일 목록

| 경로 | 설명 |
|------|------|
| `docs/PROMPT_FORWARD_T0_FROM_SIM_CSV.md` | 구현·Agent task prompt |
| `docs/REPORT_FORWARD_T0_FROM_CSV.md` | 본 보고서 |
| `simulation/tools/build_forward_scenario_from_csv.py` | 역추정 빌더 |
| `simulation/tools/promote_scenario_validated.py` | VALIDATED 승격 |
| `simulation/tools/run_forward_pipeline.sh` | 일괄 파이프라인 |
| `simulation/scenario_out/FWD_CSV_f5178_T620/` | E2E 검증 번들 |

## 부록 B. `mes_lot_release_plan` 필드 매핑

| plan 컬럼 | ARRIVAL / 기타 |
|-----------|----------------|
| `release_time` | `event_time` (절대 sim 분) |
| `product_name` | `product` |
| `route_name` | `route_id` |
| `lots_count` | 1 |
| `due_date_sim` | `detail_2.due_date_sim_min` |
| `lot_type` | `lot_id` (이름 재현) |
| `wafers_per_lot`, `priority`, `is_super_hot` | master `LotRelease` 또는 default |

**필터:** `ARRIVAL` ∧ `T0 < event_time ≤ T0 + horizon` ∧ `lot_id ∉ T0 WIP`.
