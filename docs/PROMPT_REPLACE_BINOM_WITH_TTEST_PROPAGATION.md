# [DEPRECATED — superseded by PROMPT_REFACTOR_PROPAGATION_TO_G_STAR_ANALYSIS.md]

# 패치 프롬프트: 파이프라인 A(병목 확산) — 이항검정 제거 → 과거 2h-차분 vs FORWARD t-검정 (+ Ljung-Box 독립성 게이트)

아래 블록 전체를 **시스템/역할 프롬프트**로 복사해 구현 에이전트에 붙여 넣으세요.

**목표:** 파이프라인 A(병목 확산)의 후보 선정 근거를
**이항검정(`binomtest`, k/N 병목 비율 vs p0)** 에서
**“과거 2시간 차분 분포 vs T0 기준 FORWARD 2시간 변화 분포”의 t-검정** 으로 **전면 교체**한다.
t-검정 전, 과거 차분 시계열의 **독립성을 Ljung-Box(α=0.01)** 로 먼저 검증한다.

**대상 코드:** `FAB_BEAR/simulation` 의 A 파이프라인 일체. (B=what-if, Agent 서버, 프론트는 건드리지 않는다.)

---

## 역할

당신은 `FAB_BEAR/simulation` Python 구현자입니다. A 파이프라인(확산)과 그 문서/테스트만 수정합니다.
B(what-if) 로직(`stats/whatif_effect.py`, `stat_whatif_paired_report.py`)과 G\* 산출(`tools/ml_g_star_at_t0.py`)은 **변경하지 않는다.**

---

## 변경 동기 (왜)

- 기존 이항검정은 **“T0+2h에 병목이 자주 나오는가(빈도)”** 를 묻는다 → **“병목이 확산/악화되는가”** 와 다름.
- pooled `p_null_hat`(예: 0.4188)은 자주 막히는 TG가 섞여 **배경률이 부풀려져 의미가 희석**된다.
- 우리가 알고 싶은 것: **T0를 기점으로 FORWARD 2시간 동안의 KPI 변화가, 과거 같은 길이(2시간) 변화의 자연 변동보다 유의하게 큰가(악화됐는가).**

---

## 핵심 통계 설계 (정확히 이대로 구현)

대상 KPI (TG-wide, 연속값) — 5종 고정:

```
KPIS = ["q_time_min", "wait_ratio", "wip", "available_tool_ratio", "utilization_avg"]
```

KPI별 "악화(worse)" 방향:

| KPI | 악화 방향 | t-검정 대립가설 |
|-----|-----------|-----------------|
| q_time_min | ↑ | mean(Δ_fwd) > mean(Δ_base) |
| wait_ratio | ↑ | mean(Δ_fwd) > mean(Δ_base) |
| wip | ↑ | mean(Δ_fwd) > mean(Δ_base) |
| utilization_avg | ↑ | mean(Δ_fwd) > mean(Δ_base) |
| available_tool_ratio | ↓ | mean(Δ_fwd) < mean(Δ_base) |

`H = horizon = 120분`(2시간). 분석 대상 TG = **eligible B = G\*에 없는 TG 전체**.

### (1) 과거 baseline 차분 30개 (자기상관 있음)

cold-start 이력 CSV(`--baseline-csv-dir`, 기본 `sim_csv_out`)에서, TG·KPI마다
**비중첩 2시간 차분 30개**를 T0에서 과거로 생성한다.

```
Δ_base[j] = KPI(t0 - j*H) - KPI(t0 - (j+1)*H),   j = 0,1,...,29
# 즉 (t0)-(t0-2h), (t0-2h)-(t0-4h), ..., (t0-58h)-(t0-60h)
```

- 각 시점은 `read_kpi_toolgroup_wide(..., snapshot_time, tolerance)` 로 조회(±tolerance).
- 31개 스냅샷(t0, t0-H, …, t0-30H)이 모두 있어야 30개 차분 완성. 누락 시 해당 (TG,KPI)는 `status="insufficient_history"` 로 표기하고 후보에서 제외.

### (2) FORWARD 변화 30개 (seed 간 독립)

T0 기준 FORWARD N=30 run(`runs_manifest.csv`)에서 TG·KPI마다:

```
Δ_fwd[i] = KPI_fwd_i(t0 + H) - KPI_T0,     i = 1..30
```

- `KPI_T0` (t0 시점 값)는 모든 seed가 동일한 초기 스냅샷에서 출발하므로 **baseline cold-start의 t0 값**을 공통으로 사용한다. (FORWARD run CSV에는 t0 스냅샷이 없을 수 있음 — Locked D4 참조.)
- `KPI_fwd_i(t0+H)` 는 각 forward run CSV의 t0+H(=t0+120) 스냅샷.

### (3) 독립성 게이트 — Ljung-Box (α=0.01)

baseline 차분 시계열 `Δ_base`(길이 30)에 대해 TG·KPI마다:

```
from statsmodels.stats.diagnostic import acorr_ljungbox
lb = acorr_ljungbox(Δ_base, lags=[LB_LAGS], return_df=True)
lb_p = float(lb["lb_pvalue"].iloc[-1])
lb_independent = (lb_p >= 0.01)   # H0: 자기상관 없음. 기각 못하면 독립으로 간주
```

- `LB_LAGS = 10` 고정(Locked D5).
- `lb_independent == False`(p<0.01)이면 t-검정은 수행하되 **후보 자격 박탈**(`status="autocorrelated"`), 근거에서 제외.

### (4) t-검정 — Welch 단측

```
from scipy.stats import ttest_ind
res = ttest_ind(Δ_fwd, Δ_base, equal_var=False, alternative=<dir>)
# dir: available_tool_ratio -> "less", 그 외 -> "greater"
t_stat, t_p = float(res.statistic), float(res.pvalue)
```

### (5) 다중비교 보정 — BH-FDR

eligible B × 5 KPI 의 모든 `t_p`에 대해 Benjamini-Hochberg(FDR) 보정 → `t_p_adj`.

```
from statsmodels.stats.multitest import multipletests
reject, t_p_adj, *_ = multipletests(all_t_p, alpha=ALPHA, method="fdr_bh")
```

### (6) (TG,KPI) 유의 & TG 후보 판정

```
kpi_significant = lb_independent AND (status=="ok") AND (t_p_adj < ALPHA)
TG is candidate  ⟺  유의한 KPI 개수 >= MIN_SIG_KPIS   # 기본 1 (Locked D2)
```

---

## Locked decisions (이 패치 / 기본값 — 사용자 조정 가능, 코드엔 인자로 노출)

| # | 결정 | 기본값 |
|---|------|--------|
| D1 | 후보 규칙 = `ttest_propagation` (이항/emerge 완전 제거) | — |
| D2 | TG 후보 = 유의 KPI 개수 ≥ `--min-sig-kpis` | **1** |
| D3 | 다중비교 = BH-FDR (`--multipletest fdr_bh|bonferroni|none`), `--alpha` | **fdr_bh, 0.05** |
| D4 | forward Δ의 t0 값 = baseline cold-start의 t0 스냅샷(공통) | — |
| D5 | Ljung-Box lags=`--lb-lags`, 독립성 `--independence-alpha` | **10, 0.01** |
| D6 | baseline 차분 개수 = `--n-diff` (각 H 간격) | **30** |
| D7 | KPI 목록·방향 고정(위 표) | — |
| D8 | scipy·statsmodels 필수. 없으면 명확한 에러로 종료(silent skip 금지) | — |
| D9 | `bn_t0`/`emerge`/`p_null_hat`/`binom_p`/`p0_used` 컬럼·인자 전부 제거 | — |

---

## Phase 1 — `stats/propagation.py` (핵심 재작성)

1. 삭제: `binomtest` import, `_compute_binom_p`, `candidate_rule_for_level`(binom/emerge), `emerge*` 로직, `p0_floor`/`p_null_hat`/`include_t_test`(기존 옵션) 관련 전부.
2. `PropagationConfig` 재정의:

```python
@dataclass
class PropagationConfig:
    t0: float
    horizon: float = 120.0
    tolerance: float = 1.0
    alpha: float = 0.05
    independence_alpha: float = 0.01
    lb_lags: int = 10
    n_diff: int = 30
    min_sig_kpis: int = 1
    multipletest: str = "fdr_bh"
    kpis: tuple[str, ...] = ("q_time_min", "wait_ratio", "wip",
                             "available_tool_ratio", "utilization_avg")
    thresholds: BottleneckThresholds = field(default_factory=BottleneckThresholds)
    candidate_rule: str = "ttest_propagation"
```

3. 새 함수 시그니처:

```python
def run_propagation_analysis(
    runs: list[RunMeta],            # FORWARD N runs
    g_star: set[str],
    *,
    baseline_csv_dir: Path,         # cold-start 이력 (과거 차분 소스)
    anchor_tg: Optional[str] = None,
    config: Optional[PropagationConfig] = None,
) -> tuple[pd.DataFrame, list[str]]:
    ...
```

- (1)~(6) 절차 구현. eligible B = `g_star` 여집합.
- 반환: `(summary_df, candidates)`.

4. `write_propagation_outputs(...)` handoff 블록 교체(아래 출력 스키마).

### 출력: `propagation_summary.csv` (행 = TG×KPI)

```
toolgroup, kpi, in_g_star, direction,
n_base, n_fwd, mean_base, mean_fwd, delta_mean,
lb_pvalue, lb_independent, t_stat, t_p, t_p_adj,
alpha, status, kpi_significant, anchor_tg
```
`status ∈ {ok, insufficient_history, autocorrelated, insufficient_forward}`

### 출력: `propagation_candidates.csv` (행 = 후보 TG)

```
toolgroup, n_sig_kpis, sig_kpis, min_t_p_adj, max_delta_mean, anchor_tg
```

### handoff `propagation` 블록

```json
{
  "anchor_tg": "...",
  "candidate_rule": "ttest_propagation",
  "significance_alpha": 0.05,
  "independence_test": "ljung_box",
  "independence_alpha": 0.01,
  "lb_lags": 10,
  "n_diff_baseline": 30,
  "n_runs_forward": 30,
  "kpis": ["q_time_min","wait_ratio","wip","available_tool_ratio","utilization_avg"],
  "multipletest": "fdr_bh",
  "min_sig_kpis": 1,
  "candidates": ["..."],
  "summary_csv": "propagation_summary.csv",
  "candidates_csv": "propagation_candidates.csv",
  "baseline_csv_dir": "sim_csv_out",
  "runs_manifest": "runs_manifest.csv"
}
```

---

## Phase 2 — `stats/common.py`

- scipy import에서 `binomtest` 제거(미사용 시). `ttest_ind` 사용처는 propagation에서 직접 import 가능.
- statsmodels 의존성 확인 헬퍼 추가(없으면 명확한 에러).
- `read_kpi_toolgroup_wide`는 그대로 재사용(시점별 조회). 단, **과거 30 스냅샷 반복 조회**가 비싸면 한 번 읽어 캐시하는 헬퍼 추가 권장.

---

## Phase 3 — `tools/stat_propagation_report.py`

- 제거 인자: `--level`, `--emerge-ratio`, `--p0-floor`, `--include-t-test`.
- 추가 인자: `--baseline-csv-dir`(필수), `--independence-alpha`(0.01), `--lb-lags`(10), `--n-diff`(30), `--min-sig-kpis`(1), `--multipletest`(fdr_bh), `--kpis`(콤마구분, 기본 5종). `--alpha`, `--tolerance`, `--horizon`, `--t0`, `--anchor-tg`는 유지.
- agent_notes 교체:
  ```
  "G* = ML alarm at T0 predicting bottleneck at T0+horizon.",
  "Candidate = eligible B whose FORWARD 2h KPI change exceeds historical 2h-change (Welch t-test, one-sided).",
  "Historical baseline diffs pass Ljung-Box independence (alpha=independence_alpha) before t-test.",
  "p-values BH-FDR corrected across (TG x KPI)."
  ```

---

## Phase 4 — `tools/run_stat_batch.py`

- `_propagation_handoff`: 새 `PropagationConfig`·`run_propagation_analysis(baseline_csv_dir=...)` 시그니처에 맞게 수정.
- 인자 정리(Phase 3와 동일 키), `--baseline-csv-dir` 추가.

---

## Phase 5 — `tools/run_ml_propagation_e2e.sh`

- [4/5] 호출에 `--baseline-csv-dir "$INFER_CSV"`(cold-start `sim_csv_out`) 추가, binom 인자 제거.
- [5/5] verify: `is_candidate`→후보 CSV 행수, `binom_p`/`emerge_tier` 참조 제거 → `t_p_adj`, `lb_independent`, `n_sig_kpis` 출력.

---

## Phase 6 — 테스트 `tests/test_stats_propagation_smoke.py` (재작성)

합성 KPI 디렉터리로:
1. **확산 후보 검출:** baseline 차분 ~0, forward 큰 증가 → `q_time_min` `t_p_adj < alpha`, 후보 포함.
2. **자기상관 차단:** baseline 차분에 강한 추세/주기 → `lb_independent==0` → `status="autocorrelated"`, 후보 제외.
3. **이력 부족:** 과거 스냅샷 부족 → `status="insufficient_history"`.
4. **방향성:** `available_tool_ratio` 하락이 유의일 때만 후보(반대 방향은 비유의).
5. **의존성:** statsmodels/scipy mock 제거 시 명확한 에러.

---

## Phase 7 — 스키마 & 문서

- `docs/schemas/agent_handoff_propagation.schema.json`:
  - `candidate_rule`: `const "ttest_propagation"`,
  - required에 `independence_test`, `kpis`, `significance_alpha` 추가, binom enum 제거.
- `docs/STAT_PIPELINE_AB.md`, `PROMPT_IMPLEMENT_STAT_PIPELINE_AB.md`: A 파이프라인 절을 t-검정 설계로 갱신.
- `docs/PROMPT_PATCH_L2_DEFAULT_PROPAGATION.md`: **deprecated** 표기(이항 근거 폐기).

---

## 의존성

```
pip install statsmodels   # acorr_ljungbox, multipletests
# scipy(ttest_ind) 기존 설치
```
`requirements.txt`에 `statsmodels` 추가.

---

## 검증 절차 (구현 후)

```bash
cd FAB_BEAR/simulation && source ../.env
.venv/bin/python -m pytest tests/test_stats_propagation_smoke.py -q

# 기존 30-run 재사용, ML/시뮬 스킵
.venv/bin/python tools/stat_propagation_report.py \
  --runs-manifest out/ml_propagation_e2e/runs_manifest.csv \
  --g-star-file   out/ml_propagation_e2e/g_star_T26820.json \
  --baseline-csv-dir sim_csv_out \
  --t0 26820 --horizon 120 --alpha 0.05 \
  --independence-alpha 0.01 --lb-lags 10 --n-diff 30 \
  --out-dir out/ml_propagation_e2e
```
확인: `propagation_summary.csv`(TG×KPI, `lb_independent`/`t_p_adj`/`status`),
`propagation_candidates.csv`(후보 TG), handoff `candidate_rule="ttest_propagation"`.

---

## 사용자 확정 필요 (구현 시작 전 1회 확인)

- **D2** TG 후보 기준: 유의 KPI ≥ 1 (기본) vs ≥ 2 vs 특정 primary KPI(q_time_min)만?
- **D3** 다중비교: BH-FDR(기본) vs Bonferroni vs 미적용?
- **D4** forward Δ의 t0 값: baseline cold-start 공통값(기본) vs forward run 자체 t0(있으면)?
- **D5** Ljung-Box lags=10, α=0.01 유지?
- **이항 결과 보존 여부:** 완전 삭제(기본) vs 참고 컬럼으로 summary에 잔존?
