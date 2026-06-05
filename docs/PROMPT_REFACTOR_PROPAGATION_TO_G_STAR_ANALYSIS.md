# 패치 프롬프트: 파이프라인 A 재정의 — 병목 확산(propagation) → G* KPI 원인 분석(g_star_analysis / root_cause)

아래 블록 전체를 **시스템/역할 프롬프트**로 복사해 구현 에이전트에 붙여 넣으세요.

**목표:** Track A의 제품 타겟을 **「G* 외 TG 확산 후보 선정」** 에서 **「G* TG KPI 통계 근거 → 원인 분석 Agent」** 로 전환한다.  
통계 엔진(Ljung-Box + Welch t-test + BH-FDR)은 **유지**하되, **검정 대상·handoff 계약·파이프라인 이름**을 분리·교체한다.

**대상 코드:** `FAB_BEAR/simulation` 의 Track A 일체 + 관련 schema/docs/tests/E2E.  
**건드리지 않음:** Track B (`stats/whatif_effect.py`, `stat_whatif_paired_report.py`), G\* ML 산출 로직 핵심(`ml_g_star_at_t0.py`의 proba/G\* 산출 — audit 문구만 선택 수정).

---

## 역할

당신은 `FAB_BEAR/simulation` Python 구현자입니다. propagation(확산) Track A를 **g_star_analysis / root_cause** 로 리팩터링합니다.

---

## 변경 동기 (왜)

| 이전 (확산) | 변경 후 (원인 분석) |
|-------------|---------------------|
| 질문: G\* **밖** TG 중 KPI 악화가 과거 변동보다 큰가? | 질문: ML이 알람 낸 **G\* TG** 에서 어떤 KPI가 비정상 변화했는가? |
| Agent: `bottleneck_propagation` | Agent: **`root_cause`** |
| pipeline: `propagation` | pipeline: **`g_star_analysis`** |
| 산출: `propagation_candidates` (유의 TG만) | 산출: **G\* 전원** + KPI별 `t_p_adj`, `delta_mean` (**유의 여부 무관**) |
| FDR: eligible B × KPI (~505) | FDR: **G\* × KPI only** (예: 5×5=25) |

PoC 운영 순서는 동일: **cold-start → ML G\* → FORWARD N → Track A 통계 → Agent handoff**.

---

## Locked decisions (사용자 확정 — 반드시 준수)

| # | 결정 | 값 |
|---|------|-----|
| L1 | pipeline ID | **`g_star_analysis`** |
| L2 | target_agent | **`root_cause`** |
| L3 | analysis_rule | **`ttest_g_star_analysis`** (`ttest_propagation` 폐기) |
| L4 | 검정 대상 TG | **`g_star` 집합만** full t-test + Ljung-Box |
| L5 | handoff TG | **G\* 전원** (ML `g_star_file`과 동일 목록, 유의 필터 없음) |
| L6 | handoff KPI evidence | **옵션 A:** G\*×KPI **전 행** — `t_p_adj`, `delta_mean` 등 (유의 여부와 **무관**하게 포함; 계산 불가 시 `status`+null) |
| L7 | FDR 범위 | **G\* × KPI** within only (예: \|G*\|×5; E2E 5×5=25) |
| L8 | non-G\* TG | summary에 **`status=not_in_g_star`** 참고 행만 (t-test **미수행**, 통계 컬럼 null) |
| L9 | `min_sig_kpis` / candidates 필터 | handoff에서 **제거** (후보 선정 없음) |
| L10 | T0, H, N, KPI 5종, Ljung-Box, t-test 방향 | 기존 ttest_propagation과 **동일** |
| L11 | B 파이프라인 | **변경 없음** |

---

## 핵심 통계 설계 (G\* only)

### KPI 및 악화 방향 (변경 없음)

```
KPIS = ["q_time_min", "wait_ratio", "wip", "available_tool_ratio", "utilization_avg"]
```

| KPI | 악화 방향 | t-검정 alternative |
|-----|-----------|---------------------|
| q_time_min, wait_ratio, wip, utilization_avg | ↑ | `greater` |
| available_tool_ratio | ↓ | `less` |

### 수식 (변경 없음)

```
Δ_base[j] = KPI(t0 - j·H) - KPI(t0 - (j+1)·H),   j = 0..29
Δ_fwd[i]  = KPI_fwd_i(t0 + H) - KPI_T0            (KPI_T0 = cold-start @ t0)
```

### 절차 (검정 대상만 변경)

1. **Primary loop:** `for tg in sorted(g_star):` — Ljung-Box → Welch t-test  
2. **FDR:** `status=="ok"` 인 **G\*×KPI** 행의 `t_p`만 모아 BH-FDR → `t_p_adj` (최대 \|G*\|×5개)  
3. **`kpi_significant`:** `lb_independent AND status=="ok" AND t_p_adj < alpha` — **정보용 플래그만**; handoff **필터에 사용 금지**  
4. **Reference loop:** `for tg in sorted(all_tgs - g_star):` — `status=not_in_g_star`, `in_g_star=0`, 나머지 통계 null  
5. **autocorrelated / insufficient_history** on G\*: t-test는 기존과 같이 수행 가능하나 FDR pool 제외; handoff evidence 행에는 **status와 계산된 값 그대로** 포함 (옵션 A)

---

## Phase 0 — 파일·이름 매핑

### 신규 (권장)

| 신규 파일 | 역할 |
|-----------|------|
| `simulation/stats/g_star_analysis.py` | Track A 핵심 (`run_g_star_analysis`, `write_g_star_analysis_outputs`) |
| `simulation/tools/stat_g_star_analysis_report.py` | CLI + `agent_handoff_g_star_analysis.json` |
| `docs/schemas/agent_handoff_g_star_analysis.schema.json` | JSON schema |
| `simulation/tests/test_stats_g_star_analysis_smoke.py` | smoke tests |

### 폐기·대체 (삭제 또는 thin wrapper + DeprecationWarning)

| 기존 | 처리 |
|------|------|
| `stats/propagation.py` | 로직 이전 후 **삭제** 또는 `g_star_analysis` re-export만 남기고 deprecate |
| `tools/stat_propagation_report.py` | **삭제** 또는 `stat_g_star_analysis_report.py` 호출 wrapper |
| `agent_handoff_propagation.json` | → `agent_handoff_g_star_analysis.json` |
| `propagation_summary.csv` | → `g_star_analysis_summary.csv` |
| `propagation_candidates.csv` | → **`g_star_kpi_evidence.csv`** (의미 변경, 아래 스키마) |
| `run_ml_propagation_e2e.sh` | 이름·4단계 문구를 g_star_analysis로 **갱신** (파일명 `run_ml_g_star_e2e.sh` rename 권장) |

`run_stat_batch.py`의 `--mode propagation` → **`--mode g_star_analysis`** (alias `propagation`는 1 release deprecate 후 제거).

---

## Phase 1 — `stats/g_star_analysis.py`

`propagation.py`를 기반으로 리팩터. 공통 헬퍼(`_kpi_val`, `_load_baseline_kpi_cache`)는 이전하거나 `g_star_analysis.py`에 유지.

### Config

```python
@dataclass
class GStarAnalysisConfig:
    t0: float
    horizon: float = 120.0
    tolerance: float = 1.0
    alpha: float = 0.05
    independence_alpha: float = 0.01
    lb_lags: int = 10
    n_diff: int = 30
    multipletest: str = "fdr_bh"
    kpis: tuple[str, ...] = _DEFAULT_KPIS
    analysis_rule: str = "ttest_g_star_analysis"
    # min_sig_kpis 제거
    # candidate_rule 제거
```

### Main API

```python
def run_g_star_analysis(
    runs: list[RunMeta],
    g_star: set[str],
    *,
    baseline_csv_dir: Path,
    anchor_tg: Optional[str] = None,
    config: Optional[GStarAnalysisConfig] = None,
) -> pd.DataFrame:
    """Returns summary_df (G* tested + non-G* reference rows).

    Does NOT return a filtered candidate list — G* handoff is always full g_star set.
    """
```

### 구현 체크리스트

- [ ] `test_pool = sorted(g_star)` — baseline cache·forward delta는 **이 집합만** 로드 (성능: 101→5 TG)  
- [ ] FDR correction indices: **only** rows where `in_g_star==1` and `status=="ok"`  
- [ ] non-G\* reference: `for tg in sorted(all_tgs - g_star):` append 5 KPI rows each, `status="not_in_g_star"`  
- [ ] **삭제:** `eligible_b = tg not in g_star` primary loop  
- [ ] **삭제:** informational-only G\* block (기존 338–353행 패턴) — G\*는 이제 primary  
- [ ] **삭제:** `candidates` list 산출 및 `min_sig_kpis` 필터  

### `write_g_star_analysis_outputs(...) -> dict`

```python
def write_g_star_analysis_outputs(
    out_dir: Path,
    summary: pd.DataFrame,
    *,
    cfg: GStarAnalysisConfig,
    g_star: set[str],
    anchor_tg: str,
    n_runs: int,
    runs_manifest_name: str = "runs_manifest.csv",
    baseline_csv_dir: str = "sim_csv_out",
) -> dict:
```

---

## Phase 2 — 출력 스키마

### `g_star_analysis_summary.csv` (행 = TG×KPI, 감사용 전체)

컬럼 (기존 propagation_summary와 호환 + status 확장):

```
toolgroup, kpi, in_g_star, direction,
n_base, n_fwd, mean_base, mean_fwd, delta_mean,
lb_pvalue, lb_independent, t_stat, t_p, t_p_adj,
alpha, status, kpi_significant, anchor_tg
```

`status ∈ {ok, insufficient_history, autocorrelated, insufficient_forward, not_in_g_star}`

| status | 의미 |
|--------|------|
| `ok` | G\*, Ljung-Box pass, t-test 수행, FDR 대상 |
| `autocorrelated` | G\*, Ljung-Box fail |
| `insufficient_history` | G\*, baseline 스냅샷 부족 |
| `insufficient_forward` | G\*, forward 값 부족 |
| `not_in_g_star` | non-G\* **참고 행** (통계 null) |

행 수 (E2E): **\|G*\|×5 + (106-\|G*\|)×5** ≈ 530 (G\*=5일 때 25+505)

### `g_star_kpi_evidence.csv` (Agent **주 입력** — 옵션 A)

**행 = G\* × KPI 전부** (`summary`에서 `in_g_star==1` 필터). 유의 여부로 **행 제외 금지**.

```
toolgroup, kpi, direction,
n_base, n_fwd, mean_base, mean_fwd, delta_mean,
lb_pvalue, lb_independent, t_stat, t_p, t_p_adj,
status, kpi_significant, anchor_tg
```

- E2E: **25 rows** (5 TG × 5 KPI)  
- `kpi_significant`는 Agent 참고용; **필수 필터 아님**

### handoff JSON — `agent_handoff_g_star_analysis.json`

```json
{
  "version": "1.0",
  "pipeline": "g_star_analysis",
  "target_agent": "root_cause",
  "generated_at": "...",
  "t0_sim_minute": 26820,
  "horizon_minutes": 120,
  "n_runs": 30,
  "label_rule": "assign_bottleneck_labels / REPORT §4.3",
  "g_star_toolgroups": ["DE_BE_66", "DefMEt_FE_118", "..."],
  "runs_manifest": "runs_manifest.csv",
  "g_star_analysis": {
    "anchor_tg": "DefMEt_FE_118",
    "analysis_rule": "ttest_g_star_analysis",
    "significance_alpha": 0.05,
    "independence_test": "ljung_box",
    "independence_alpha": 0.01,
    "lb_lags": 10,
    "n_diff_baseline": 30,
    "n_runs_forward": 30,
    "fdr_scope": "g_star_x_kpi",
    "fdr_n_hypotheses": 25,
    "kpis": ["q_time_min", "wait_ratio", "wip", "available_tool_ratio", "utilization_avg"],
    "multipletest": "fdr_bh",
    "g_star_toolgroups": ["..."],
    "summary_csv": "g_star_analysis_summary.csv",
    "evidence_csv": "g_star_kpi_evidence.csv",
    "baseline_csv_dir": "sim_csv_out",
    "runs_manifest": "runs_manifest.csv"
  },
  "agent_notes": [
    "G* = ML alarm at T0 predicting bottleneck at T0+horizon.",
    "Analysis pool = G* only; non-G* rows in summary are status=not_in_g_star (reference).",
    "Handoff includes ALL G* x KPI evidence (t_p_adj, delta_mean) regardless of kpi_significant.",
    "p-values BH-FDR corrected within G* x KPI only."
  ]
}
```

**금지:** `propagation` 키, `candidates` 배열(유의 TG subset), `candidate_rule`, `min_sig_kpis` in handoff.

**선택:** JSON 내 `evidence` 배열에 CSV와 동일 25건 embed (DB 없을 때 Agent 편의). CSV 포인터는 필수.

---

## Phase 3 — `tools/stat_g_star_analysis_report.py`

`stat_propagation_report.py` 대체.

```bash
python tools/stat_g_star_analysis_report.py \
  --runs-manifest out/ml_propagation_e2e/runs_manifest.csv \
  --g-star-file out/ml_propagation_e2e/g_star_T26820.json \
  --baseline-csv-dir sim_csv_out \
  --t0 26820 --horizon 120 --n-runs 30 \
  --alpha 0.05 --independence-alpha 0.01 --lb-lags 10 --n-diff 30 \
  --out-dir out/ml_g_star_e2e
```

- 제거 인자: `--min-sig-kpis`  
- default handoff: `{out-dir}/agent_handoff_g_star_analysis.json`  
- stdout: `G* evidence rows: 25 -> agent_handoff_g_star_analysis.json`

---

## Phase 4 — `tools/run_stat_batch.py`

- `--mode g_star_analysis` (replace `propagation`)  
- `_propagation_handoff` → `_g_star_analysis_handoff`  
- handoff payload: `pipeline`, `target_agent`, `g_star_analysis` block  
- `merge_handoff`: `propagation` 키 → `g_star_analysis` (optional combined handoff)  
- `--min-sig-kpis` 제거  

---

## Phase 5 — E2E `run_ml_g_star_e2e.sh` (구 `run_ml_propagation_e2e.sh`)

1. ML G\* @ T0 (변경 없음)  
2. Audit: G\* 목록 출력 (eligible B 문구 → “analysis pool = G*”)  
3. FORWARD N×  
4. **`stat_g_star_analysis_report.py`** 호출  
5. 요약: `g_star_kpi_evidence.csv` rows = \|G*\|×5, `fdr_n` = ok rows within G\*  

환경변수 `OUT_DIR` 기본값 `out/ml_g_star_e2e` 권장 (기존 `out/ml_propagation_e2e`와 분리 또는 동일 dir 허용).

---

## Phase 6 — `tools/ml_g_star_at_t0.py` (문구만)

- audit CSV `eligible_B` 컬럼은 ML 감사용으로 **유지 가능**  
- print 문구: `"Eligible B (propagation test pool)"` → `"G* analysis pool: N TG (see g_star_analysis pipeline)"`  
- `g_star_T*.json` 포맷 **변경 없음**

---

## Phase 7 — Schema & docs

### `docs/schemas/agent_handoff_g_star_analysis.schema.json`

```json
{
  "pipeline": { "const": "g_star_analysis" },
  "target_agent": { "const": "root_cause" },
  "g_star_analysis": {
    "required": [
      "anchor_tg", "analysis_rule", "g_star_toolgroups",
      "summary_csv", "evidence_csv", "significance_alpha",
      "independence_test", "fdr_scope", "kpis", "multipletest"
    ],
    "properties": {
      "analysis_rule": { "const": "ttest_g_star_analysis" },
      "fdr_scope": { "const": "g_star_x_kpi" }
    }
  }
}
```

### 문서 갱신

- `docs/STAT_PIPELINE_AB.md` — Track A를 g_star_analysis / root_cause로 재작성  
- `docs/REPORT_STAT_PIPELINE_AB_20260605.md` — 상단에 “superseded by g_star_analysis” 배너 또는 신규 보고서  
- `docs/CSV_DB_MAPPING.md` — evidence CSV → DB 테이블 매핑 추가  
- `docs/PROMPT_REPLACE_BINOM_WITH_TTEST_PROPAGATION.md` — 상단 deprecated 노트 (확산 타겟 폐기)

---

## Phase 8 — Tests

`tests/test_stats_g_star_analysis_smoke.py` (기존 propagation smoke **이전·수정**):

| 테스트 | 검증 |
|--------|------|
| `test_g_star_only_tested` | g_star={TG1}일 때 TG1만 `status!=not_in_g_star` |
| `test_non_g_star_reference_rows` | non-G\* → `status=not_in_g_star`, `t_p` null |
| `test_fdr_scope_g_star_only` | G\* 2×2 KPI mock; FDR n_hypotheses=4 not 106×5 |
| `test_evidence_includes_all_g_star_kpis` | evidence CSV rows = \|g_star\|×\|kpis\| regardless of kpi_significant |
| `test_ljung_box_blocks_fdr_not_evidence_row` | autocorrelated G\* row still in evidence CSV with status |
| `test_handoff_no_candidates_key` | JSON에 `candidates` 없음, `g_star_toolgroups` == g_star |

```bash
cd FAB_BEAR/simulation
.venv/bin/python -m pytest tests/test_stats_g_star_analysis_smoke.py -q
```

기존 `test_stats_propagation_smoke.py`는 **삭제** 또는 g_star_analysis로 rename.

---

## Phase 9 — `stats/common.py` — `merge_handoff`

```python
def merge_handoff(
    g_star_analysis: Optional[dict],  # was propagation
    whatif: Optional[dict],
    ...
) -> dict:
    return {
        ...
        "g_star_analysis": g_star_analysis,
        "whatif": whatif,
    }
```

`agent_handoff.schema.json` top-level `propagation` → `g_star_analysis`.

---

## 완료 기준 (체크리스트)

- [ ] `run_g_star_analysis` — G\* only test + non-G\* `not_in_g_star` reference  
- [ ] FDR within G\*×KPI only (`fdr_scope=g_star_x_kpi`)  
- [ ] `g_star_kpi_evidence.csv` — all G\*×KPI, no significance filter  
- [ ] `agent_handoff_g_star_analysis.json` — `pipeline=g_star_analysis`, `target_agent=root_cause`  
- [ ] propagation naming/candidates/min_sig_kpis **제거**  
- [ ] `run_stat_batch.py --mode g_star_analysis`  
- [ ] E2E shell + stat CLI 동작  
- [ ] schema + smoke tests pass  
- [ ] Track B unchanged  

---

## E2E 검증 (구현 후 실행)

```bash
cd FAB_BEAR/simulation && source ../.env

# FORWARD reuse 가능 시
SKIP_ML=1 SKIP_SIM=1 N_RUNS=30 ./tools/run_ml_g_star_e2e.sh

# 또는 stat only
python tools/stat_g_star_analysis_report.py \
  --runs-manifest out/ml_propagation_e2e/runs_manifest.csv \
  --g-star-file out/ml_propagation_e2e/g_star_T26820.json \
  --baseline-csv-dir sim_csv_out \
  --t0 26820 --horizon 120 \
  --out-dir out/ml_g_star_e2e
```

**기대 (G\*=5, KPI=5):**

| 산출물 | 기대 |
|--------|------|
| `g_star_kpi_evidence.csv` | **25 rows** |
| `g_star_analysis_summary.csv` | **530 rows** (25 tested + 505 not_in_g_star) |
| handoff `g_star_toolgroups` | **5개** (ML G\*와 동일) |
| `g_star_analysis.fdr_n_hypotheses` | ≤25 (ok status G\*×KPI 수) |

**더 이상 기대하지 않음:** `propagation_candidates` 27 TG, `candidates` 유의 필터.

---

## 구현 순서 권장

1. `g_star_analysis.py` + unit logic  
2. `stat_g_star_analysis_report.py` + schema  
3. tests  
4. `run_stat_batch.py` + `merge_handoff`  
5. E2E shell rename  
6. docs deprecate propagation  
7. delete/deprecate `propagation.py`, `stat_propagation_report.py`  

---

## 주의 (흔한 실수)

1. **handoff에서 G\* 필터링 금지** — 옵션 A는 ML G\* 전원 + 모든 KPI 행.  
2. **FDR을 505개에 걸지 말 것** — 반드시 G\*×KPI만.  
3. **pipeline/target_agent 혼용 금지** — `propagation` / `bottleneck_propagation` 잔존 코드 검색 후 제거.  
4. **B는 `propagation_candidates`를 읽지 않음** — 이번 변경 후 evidence CSV명만 바뀌어도 B 무관.  
5. non-G\* reference 행에 t-test 돌리지 말 것 (낭비 + 의미 혼동).

---

*프롬프트 버전: 2026-06-05 · propagation → g_star_analysis / root_cause · 옵션 A handoff · FDR within G\*×KPI · not_in_g_star reference*
