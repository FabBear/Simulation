# 구현 프롬프트: Trigger E2E 오케스트레이션 (snapshot → clone → 병렬 sim → Agent handoff JSON)

아래 블록 전체를 **시스템/역할 프롬프트**로 복사해 구현 에이전트에 붙여 넣으세요.

**목표:** 지금까지 **수동 CLI**로 단계별 실행하던 Track A(FORWARD 원인 분석) / Track B(WHAT-IF 대응안 검정) 파이프라인을, **하나의 Trigger 진입점**으로 묶어 **AI Agent가 통계 검정 결과 JSON(`agent_handoff_*.json`)을 자동으로 받도록** 연결한다.

**핵심 원칙:** 새 통계 수식 · FabEnv · clone/sim/stat 엔진은 **건드리지 않는다**. 이미 구현된 building block을 **순서대로 호출하는 오케스트레이션 레이어만 추가**한다.

---

## 역할

당신은 `FAB_BEAR/simulation` Python 구현자입니다. **L2 Trigger 앞단(snapshot 생성 → DB load)** 을 기존 Monte Carlo 오케스트레이터(`run_monte_carlo_batch.py`)에 연결해 **end-to-end 자동 실행**을 완성합니다.

---

## 경계 (반드시 준수)

| 액터 | 책임 | 우리가 구현? |
|------|------|:---:|
| **ML / Rule** | T0 시점 병목 예측 → FORWARD trigger 발화 | ❌ (외부, 입력만 받음) |
| **대응안 Agent** | WHAT-IF `actions[]` 1건 제안 | ❌ (외부, 입력만 받음) |
| **root_cause / whatif_verification Agent** | handoff JSON 수신 후 추론 | ❌ |
| **L2 Trigger (본 프롬프트)** | snapshot → load → clone → 병렬 sim → stat → handoff JSON | ✅ |

- Agent는 **`_R01..R30` replica · 30 CSV 폴더 · MES snapshot row를 직접 만들지 않는다.**
- 본 작업은 Agent 로직을 구현하는 것이 **아니라**, Agent가 받을 JSON을 **자동 생성하는 파이프라인**을 잇는 것이다.

---

## 건드리지 않음 (Locked)

- `fab_env.py`, `core/runner.py`, `run_sim_forward_once.py` (엔진)
- `stats/g_star_analysis.py`, `stats/whatif_effect.py`, `stats/common.py` (통계 수식)
- `tools/clone_mes_scenarios_for_monte_carlo.py` (clone)
- `tools/run_stat_batch.py` (병렬 sim + handoff)
- handoff JSON 스키마 (`docs/schemas/agent_handoff_*.schema.json`) — 이미 인라인 통계(`g_star_kpi_evidence`, `whatif_paired_results`)로 확정됨
- Agent 추론 로직, `data_labeling.ipynb`

---

## 이미 구현된 building block (SSOT, 호출만 한다)

| 단계 | 파일 | 핵심 인자 |
|------|------|-----------|
| FORWARD snapshot bundle | `tools/build_forward_scenario_from_csv.py` | `--sim-csv-dir --run-id --t0 --horizon --scenario-id --out-dir` |
| WHAT-IF bundle | `tools/make_whatif_scenario_bundle.py` | `--base-dir --whatif-scenario-id --baseline-scenario-id --t0 --horizon --whatif-actions` |
| DB load (DRAFT) | `load_mes_scenario.py` | `--scenario-id --mode --t0 --horizon [--baseline] --wip --tools --queues --releases [--whatif]` |
| clone N replicas | `tools/clone_mes_scenarios_for_monte_carlo.py` | `--source-scenario-id --suffix-pattern --n-runs --on-conflict` |
| 병렬 sim + stat + handoff | `tools/run_monte_carlo_batch.py` | `--track {g_star_analysis,whatif} --template-scenario-id --t0 --horizon --n-runs --parallel --out-dir` |

> `build_forward_scenario_from_csv.py` 는 `out_dir/`에 `mes_wip_snapshot.csv`, `mes_tool_snapshot.csv`, `mes_tool_queue_snapshot.csv`, `mes_lot_release_plan.csv` 를 출력한다. `load_mes_scenario.py` 의 `--wip/--tools/--queues/--releases` 인자에 그대로 매핑된다.

---

## 현재 gap (연결 안 된 지점)

`run_monte_carlo_batch.py` 는 **template이 이미 DB에 있다고 가정**한다. 그 앞단(snapshot 생성 + load)이 수동이다. 본 프롬프트는 이 앞단을 자동화한다.

```
[현재 수동]  build_forward / make_whatif → load_mes_scenario
[자동화 됨]  → clone → run_stat_batch → agent_handoff_*.json
```

---

## Phase 1 — `tools/trigger_forward_pipeline.py` (Track A 진입점, 신규)

**ML이 T0 병목을 예측하면 호출**하는 단일 진입점. snapshot부터 handoff JSON까지.

### 입력 (CLI 또는 JSON payload)

```json
{
  "sim_csv_dir": "sim_csv_out/cold_start",
  "run_id": "<cold-start run id>",
  "t0_sim_minute": 26820,
  "horizon_minutes": 120,
  "scenario_id": "FWD_BASE_T26820",
  "g_star_file": "out/ml_g_star_e2e/g_star.json",
  "n_runs": 30,
  "parallel": 8,
  "out_dir": "out/forward_trigger_T26820"
}
```

### 수행 순서

1. **snapshot bundle**: `build_forward_scenario_from_csv.py` → `out_dir/bundle/`
2. **DB load (DRAFT)**: `load_mes_scenario.py --mode FORWARD --scenario-id <template>` (bundle CSV 매핑)
3. **MC clone + 병렬 FORWARD sim + stat + handoff**: `run_monte_carlo_batch.py --track g_star_analysis --template-scenario-id <template> ...`
4. 결과: `out_dir/agent_handoff_g_star_analysis.json` 경로를 stdout에 JSON으로 출력 (Agent/Trigger 회신용)

### 규칙

- 각 단계 `subprocess.run(..., cwd=_ROOT)`; non-zero exit → 즉시 중단(exit code 전파).
- `--dry-run`: DB write 없이 각 단계 커맨드를 stdout에 출력만.
- `--skip-snapshot` / `--skip-load`: 이미 만들어진 단계 재사용 (idempotent E2E 디버깅용).
- snapshot bundle이 비어있거나 load row count 0 → fail-fast.
- 최종 stdout (성공 시):

```json
{
  "track": "g_star_analysis",
  "template_scenario_id": "FWD_BASE_T26820",
  "replica_scenario_ids": ["FWD_BASE_T26820_R01", "...", "FWD_BASE_T26820_R30"],
  "handoff_path": "out/forward_trigger_T26820/agent_handoff_g_star_analysis.json",
  "runs_manifest": "out/forward_trigger_T26820/runs_manifest.csv"
}
```

---

## Phase 2 — `tools/trigger_whatif_pipeline.py` (Track B 진입점, 신규)

**대응안 Agent가 actions 1건을 제출하면 호출**하는 단일 진입점.

### 입력 (Agent submit)

```json
{
  "baseline_scenario_id": "FWD_BASE_T26820",
  "baseline_bundle_dir": "scenario_out/FWD_BASE_T26820",
  "reuse_baseline_manifest": "out/forward_trigger_T26820/runs_manifest.csv",
  "whatif_scenario_id": "FWD_WHATIF_T26820_RANK1",
  "t0_sim_minute": 26820,
  "horizon_minutes": 120,
  "whatif_actions_csv": "agent_actions/rank1_actions.csv",
  "focus_scopes": "Diffusion_FE_120#1",
  "n_runs": 30,
  "parallel": 8,
  "out_dir": "out/whatif_trigger_rank1"
}
```

### 수행 순서

1. **WHAT-IF bundle**: `make_whatif_scenario_bundle.py --base-dir <baseline_bundle_dir> --whatif-actions <csv>` → `out_dir/bundle/`
2. **DB load (DRAFT)**: `load_mes_scenario.py --mode WHATIF --baseline <baseline_scenario_id> --whatif <action csv>` (bundle CSV 매핑)
3. **MC clone + 병렬 WHAT-IF sim (baseline manifest 재사용) + paired t + handoff**: `run_monte_carlo_batch.py --track whatif --template-scenario-id <whatif> --reuse-baseline-manifest <...> --baseline-scenario-id <...>`
4. 결과: `out_dir/agent_handoff_whatif.json` 경로 stdout JSON 출력

### 규칙

- baseline manifest 미존재/ok row < n_runs → fail-fast (baseline 먼저 Track A로 생성).
- 나머지 규칙(Phase 1과 동일): dry-run, skip 플래그, fail-fast, 최종 JSON 회신.
- baseline sim **재실행 금지** (Locked: what-if는 baseline manifest 재사용).

---

## Phase 3 — 공통 헬퍼

중복 줄이기 위해 `tools/_trigger_common.py`(또는 두 진입점이 공유하는 함수) 권장:

- `run_step(cmd: list[str], *, dry_run: bool) -> int` — 출력/에러 통일, cwd=_ROOT.
- `bundle_csv_paths(bundle_dir) -> dict` — wip/tools/queues/releases/whatif 경로 매핑(존재하는 것만).
- `emit_result_json(...)` — 최종 회신 JSON 직렬화(`allow_nan=False`).
- replica id 목록은 `clone_mes_scenarios_for_monte_carlo.expand_replica_scenario_ids()` 재사용.

---

## Phase 4 — 테스트

신규: `simulation/tests/test_trigger_pipeline_smoke.py`

| Test | 방법 |
|------|------|
| `test_forward_pipeline_dry_run_chain` | `trigger_forward_pipeline.py --dry-run` → stdout에 build_forward, load_mes_scenario, run_monte_carlo_batch 커맨드 3개 순서대로 포함 |
| `test_whatif_pipeline_dry_run_chain` | `trigger_whatif_pipeline.py --dry-run` → make_whatif, load, run_monte_carlo_batch 포함 |
| `test_whatif_fail_fast_missing_baseline_manifest` | 존재하지 않는 manifest → exit 1, handoff 미생성 |
| `test_result_json_shape` | dry-run 결과 JSON에 `handoff_path`, `template_scenario_id` 키 존재 |
| `test_bundle_csv_paths_only_existing` | 일부 CSV만 있는 디렉터리 → 존재하는 키만 반환 |

기존 `test_clone_mes_scenarios_smoke.py`, `test_run_stat_batch_promote_smoke.py`, `test_handoff_json_contract.py` 는 그대로 통과해야 한다.

---

## Phase 5 — 문서

| 파일 | 변경 |
|------|------|
| `docs/TRIGGER_CONTRACT.md` | Appendix에 "E2E Trigger 진입점" 절: 두 pipeline 커맨드 + 입력/출력 JSON |
| `docs/REPORT_STAT_PIPELINE_AB_20260605.md` | Track A/B 실행 절에 "수동 단계 → trigger 한 줄" 업데이트 |

---

## E2E 검증 (구현 후)

```bash
cd FAB_BEAR/simulation

# Track A: dry-run 체인 확인
.venv/bin/python tools/trigger_forward_pipeline.py \
  --sim-csv-dir sim_csv_out/cold_start \
  --run-id <run_id> \
  --t0 26820 --horizon 120 \
  --scenario-id FWD_BASE_T26820 \
  --g-star-file out/ml_g_star_e2e/g_star.json \
  --n-runs 30 --parallel 8 \
  --out-dir out/forward_trigger_T26820 \
  --dry-run

# Track B: dry-run 체인 확인 (Track A manifest 재사용)
.venv/bin/python tools/trigger_whatif_pipeline.py \
  --baseline-scenario-id FWD_BASE_T26820 \
  --baseline-bundle-dir scenario_out/FWD_BASE_T26820 \
  --reuse-baseline-manifest out/forward_trigger_T26820/runs_manifest.csv \
  --whatif-scenario-id FWD_WHATIF_T26820_RANK1 \
  --t0 26820 --horizon 120 \
  --whatif-actions agent_actions/rank1_actions.csv \
  --focus-scopes "Diffusion_FE_120#1" \
  --n-runs 30 --parallel 8 \
  --out-dir out/whatif_trigger_rank1 \
  --dry-run

# 실제 실행: --dry-run 제거 후 실행, 최종 handoff JSON 확인
.venv/bin/python -c "
import json
h = json.load(open('out/whatif_trigger_rank1/agent_handoff_whatif.json'))
assert h['whatif']['whatif_paired_results'], 'inline stat rows missing'
assert h.get('monte_carlo',{}).get('n_runs') == 30
print('OK', h['target_agent'])
"
```

---

## 완료 기준 (체크리스트)

- [ ] `tools/trigger_forward_pipeline.py` — snapshot → load → MC → handoff (Track A)
- [ ] `tools/trigger_whatif_pipeline.py` — bundle → load → MC(baseline reuse) → handoff (Track B)
- [ ] `--dry-run` 으로 3단계 커맨드 체인 출력
- [ ] fail-fast: snapshot/load 실패, baseline manifest 부족 시 즉시 중단
- [ ] 최종 stdout 회신 JSON(`handoff_path`, `replica_scenario_ids`)
- [ ] pytest smoke 통과 (신규 + 기존)
- [ ] `TRIGGER_CONTRACT.md` E2E 진입점 절 추가

## 안티패턴 (하지 말 것)

1. clone/sim/stat 엔진 재작성 — 호출만.
2. Agent 추론·actions 생성 로직 구현 — 입력으로만 받음.
3. handoff JSON에 CSV 포인터 재도입 — 인라인 통계(`g_star_kpi_evidence`, `whatif_paired_results`) 유지.
4. baseline sim 재실행 (what-if) — manifest 재사용.
5. Agent가 replica/snapshot을 만들도록 요구 — Trigger 책임.

---

*프롬프트 버전: 2026-06-07 · L2 Trigger E2E 연결 · snapshot→load→MC→handoff · Agent 입력/출력 JSON only*
