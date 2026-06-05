# 패치 프롬프트: 확산 후보 = L2 이항검정(α=0.05) 기본화 · L1(80%) 근거 제거

아래 블록 전체를 **시스템/역할 프롬프트**로 복사해 구현 에이전트에 붙여 넣으세요.

**목표:** 파이프라인 A(확산)의 **확산 후보(`propagation_candidates`) 선정 근거**를
**L1 emerge(k/N ≥ 0.8) → L2 이항검정(`binomtest`, 일측 greater, α=0.05)** 으로 바꾼다.
L1(80% 컷)은 **선정 근거에서 제거**하고, 남기더라도 **참고용 tier 라벨**로만 둔다.

**근거 문서:** `docs/REPORT_COMPARE_BINOMIAL_VS_TTEST.md` (L2 §; p₀ = max(p̂_null, 0.1), α=0.05).
**대상 코드:** 이미 구현된 `FAB_BEAR/simulation/stats/propagation.py` 외 A 파이프라인 일체.

---

## 역할

당신은 `FAB_BEAR/simulation` Python 구현자입니다.
**Agent 서버·Spring·프론트·what-if(B) 로직은 수정하지 않는다.** A 파이프라인과 그 문서/테스트만 고친다.

---

## 변경 동기 (왜)

- L1의 「30회 중 80% 이상 병목」은 **합의된 발표용 강(强) 컷**일 뿐 **통계적 근거가 아니다.**
- 합의된 정식 근거는 **L2**: 같은 N run에서 G\* 밖 TG의 T0+2h 병목 비율로 **p̂_null** 추정 →
  **p₀ = max(p̂_null, 0.1)** → `binomtest(k_B, N, p=p₀, alternative='greater')` →
  **p-value < α(0.05)** 이면 「우연으로 보기 어려운 확산」으로 **H₀ 기각**.
- 현재 코드는 `binom_p`를 **계산만** 하고, 후보는 여전히 `emerge(0.8)`로 고른다 → **불일치**. 이걸 바로잡는다.

---

## Locked decisions (이 패치)

| # | 결정 |
|---|------|
| P1 | **확산 후보 기본 규칙 = L2**: `B ∉ G*` AND `¬bn(B@T0)` AND `binom_p < alpha` |
| P2 | **alpha 기본 0.05** (`--alpha`, 일측 greater) |
| P3 | **p₀ = max(p̂_null, p0_floor)**, `p0_floor` 기본 0.1 (변경 없음) |
| P4 | **L1(emerge 0.8)은 후보 근거에서 제외.** `emerge` 컬럼은 **참고 tier**로만 유지(`emerge_tier`), 후보 목록·Agent `candidates`에는 영향 없음 |
| P5 | **scipy 필수(L2 기본).** `binomtest` import 실패 시 **명확한 에러로 종료**(silent skip 금지). `--level L1` 명시한 경우에만 binom 없이 emerge 기반 fallback 허용 |
| P6 | `--level` 기본값 **L2** 유지. `L1`은 **레거시/데모 전용**으로만 동작(후보=emerge), 문서에 「근거 아님」 명시 |
| P7 | Agent handoff에 **`candidate_rule`**, **`significance_alpha`** 필드 추가 |

---

## SSOT (읽고 재사용 — 이미 존재)

| 구분 | 경로 |
|------|------|
| A 코어 | `simulation/stats/propagation.py` (`run_propagation_analysis`, `write_propagation_outputs`, `PropagationConfig`) |
| A CLI | `simulation/tools/stat_propagation_report.py` |
| 배치 | `simulation/tools/run_stat_batch.py` (`_propagation_handoff`) |
| 공통 | `simulation/stats/common.py` (`binomtest` import, manifest) |
| 테스트 | `simulation/tests/test_stats_propagation_smoke.py` |
| 구현 프롬프트(본문) | `docs/PROMPT_IMPLEMENT_STAT_PIPELINE_AB.md` (Locked #5, Phase 2) |
| 통계 리포트 | `docs/REPORT_COMPARE_BINOMIAL_VS_TTEST.md` (L2) |
| 운영 문서 | `docs/STAT_PIPELINE_AB.md` |

---

## Phase 1 — `stats/propagation.py`

### 1-1. `PropagationConfig`

```python
@dataclass
class PropagationConfig:
    t0: float
    horizon: float = 120.0
    tolerance: float = 1.0
    p0_floor: float = 0.1
    alpha: float = 0.05                 # NEW
    emerge_ratio_cut: float = 0.8       # 참고 tier 전용 (후보 근거 아님)
    candidate_rule: str = "binom_L2"    # NEW: "binom_L2" | "emerge_L1"(legacy)
    thresholds: BottleneckThresholds = field(default_factory=BottleneckThresholds)
    level: str = "L2"
    include_t_test: bool = False
```

- `level == "L2"`(기본) 또는 `"L3"` → `candidate_rule = "binom_L2"`.
- `level == "L1"`(레거시) → `candidate_rule = "emerge_L1"` 로만 fallback 허용.

### 1-2. 후보 선정 로직 교체

현재 (제거 대상):

```python
emerge = (not in_g) and (not bn0) and (rate >= cfg.emerge_ratio_cut)
...
if emerge:
    tier = "emerge"
    if not in_g:
        candidates.append(tg)
```

변경 후 (핵심):

```python
eligible = (not in_g) and (not bn0)            # B ∉ G*, T0 비병목
emerge = eligible and (rate >= cfg.emerge_ratio_cut)   # 참고 tier 라벨 전용

is_candidate = False
if cfg.candidate_rule == "binom_L2":
    if binomtest is None:
        raise RuntimeError("scipy required for L2 candidate rule; install scipy or use --level L1")
    is_candidate = eligible and (binom_p is not None) and (binom_p < cfg.alpha)
elif cfg.candidate_rule == "emerge_L1":     # legacy/demo only
    is_candidate = emerge

tier = ""
if is_candidate:
    tier = "strong" if emerge else "significant"
    candidates.append(tg)
elif emerge:
    tier = "emerge_only"   # 80%는 넘지만 L2 유의 아님 (참고)
```

- `binom_p`는 **모든 eligible TG에 대해 계산**(이미 일측 greater, p=p0_used). L1 레거시 경로에서도 가능하면 계산해 CSV에 남긴다.
- `eligible` 아닌 TG(=G\* 안 또는 T0 병목)는 후보 불가 — 기존 규칙 유지.

### 1-3. 출력 컬럼 (`propagation_summary.csv`)

기존 + **`is_candidate`**, **`candidate_rule`**, **`alpha`** 추가. 권장 순서:

```
toolgroup, in_g_star, k_bn_t2h, bn_rate_t2h, bn_t0,
p_null_hat, p0_used, binom_p, alpha, is_candidate,
candidate_rule, emerge, emerge_tier, anchor_tg, t_vs_t0_optional_p
```

### 1-4. `write_propagation_outputs`

- `propagation_candidates.csv` = `summary[summary["is_candidate"] == 1]` (기존 `emerge==1` 대체).
- 반환 dict에 추가: `"candidate_rule"`, `"significance_alpha": cfg.alpha`.
- 기존 `"emerge_ratio_cut"`는 참고용으로 유지.

---

## Phase 2 — CLI `tools/stat_propagation_report.py`

| Flag | 변경 |
|------|------|
| `--level` | 기본 `L2` 유지. help에 「L1=legacy emerge(근거 아님)」 명시 |
| `--alpha` | **NEW**, 기본 `0.05` |
| `--emerge-ratio` | 유지하되 help에 「참고 tier 전용, 후보 근거 아님」 |
| `--p0-floor` | 유지 |

- `PropagationConfig(..., alpha=args.alpha, candidate_rule=("emerge_L1" if args.level=="L1" else "binom_L2"))`.
- handoff payload `propagation` 블록에 `candidate_rule`, `significance_alpha` 포함(write 출력 dict 그대로 전달).

---

## Phase 3 — 배치 `tools/run_stat_batch.py`

- `_propagation_handoff`에서 `PropagationConfig`에 `alpha`, `candidate_rule` 반영.
- 새 CLI 플래그 `--alpha`(기본 0.05) 추가 → cfg로 전달.
- `--level` 기본 `L2` 확인(현재 문자열 기본값 점검).

---

## Phase 4 — Agent handoff / 스키마

`agent_handoff_propagation.json`의 `propagation` 블록 예:

```json
"propagation": {
  "anchor_tg": "Diffusion_FE_120",
  "p_null_hat": 0.07,
  "p0_floor": 0.1,
  "candidate_rule": "binom_L2",
  "significance_alpha": 0.05,
  "emerge_ratio_cut": 0.8,
  "candidates": ["Etch_B"],
  "summary_csv": "propagation_summary.csv",
  "candidates_csv": "propagation_candidates.csv"
}
```

- `docs/schemas/agent_handoff_propagation.schema.json`: `propagation.required`에 `candidate_rule`, `significance_alpha` 추가.
- `agent_notes`에 한 줄 추가: `"Candidates use one-sided binomial test (p0=max(p_hat_null,0.1)) at alpha; 80% emerge is reference only."`

---

## Phase 5 — 본문 프롬프트 동기화 `docs/PROMPT_IMPLEMENT_STAT_PIPELINE_AB.md`

- **Locked #5** 수정:
  > 확산: `B ∉ G*` & `¬bn(B@T0)` & **binomtest(k_B, N, p=max(p̂_null,0.1), greater) < α(0.05)** → 후보. **emerge(k/N≥0.8)는 참고 tier**(근거 아님).
- **Phase 2 알고리즘** 블록의 `emerge` 기반 `propagation_candidates` 정의를 **binom 기준**으로 교체.
- 출력 컬럼 목록에 `alpha`, `is_candidate`, `candidate_rule` 추가.
- CLI 표에 `--alpha` 추가.

---

## Phase 6 — 문서 `docs/STAT_PIPELINE_AB.md`

- Review Q&A의 「p₀」 항목을 **「후보 = L2 이항검정 α=0.05; 80%는 참고」**로 갱신.
- L1은 **legacy/demo** 라고 표기.

---

## Phase 7 — 테스트

`tests/test_stats_propagation_smoke.py` 갱신/추가:

1. **L2 후보(양성):** G\* 밖·T0 비병목 TG가 N회 중 충분히 많이 병목 → `binom_p < 0.05` → `is_candidate=1`, `candidates`에 포함.
   - 합성 데이터로 p̂_null을 낮게(다른 TG는 거의 병목 0) 만들어 p₀=0.1 부근, 대상 TG는 k가 커서 유의하도록 구성.
2. **emerge≥0.8 이지만 L2 비유의(경계):** `is_candidate=0`, `emerge_tier="emerge_only"` 확인(가능한 합성).
3. **scipy 부재 시 L2 → RuntimeError** (monkeypatch로 `binomtest=None`).
4. 기존 smoke의 `emerge` 단독 단언은 **`is_candidate`** 기준으로 교체.

CI-friendly(DB·full sim 불필요) 유지. 실행:

```bash
cd FAB_BEAR/simulation
.venv/bin/python -m pytest tests/test_stats_propagation_smoke.py tests/test_stats_common.py -q
```

---

## 비목표

- B(what-if) paired 로직·CLI 변경.
- `fab_env.py`·시뮬 변경.
- 다중검정 보정(FDR) 도입 — 별도 이슈(원하면 `--fdr` 후속).
- N=30 full sim 필수 실행(스모크만).

---

## 완료 기준 (체크리스트)

- [ ] `PropagationConfig`에 `alpha`, `candidate_rule` 추가, 기본 L2=binom
- [ ] 후보 선정 = `binom_p < alpha` (eligible 한정), emerge는 tier 라벨만
- [ ] `propagation_summary.csv`에 `alpha`, `is_candidate`, `candidate_rule`
- [ ] `propagation_candidates.csv` = `is_candidate==1`
- [ ] CLI `--alpha`(stat_propagation_report, run_stat_batch)
- [ ] handoff/스키마에 `candidate_rule`, `significance_alpha`
- [ ] 본문 프롬프트 Locked #5·Phase 2 동기화
- [ ] scipy 부재 시 L2 RuntimeError
- [ ] smoke tests pass (양성·경계·scipy 부재)

---

## 검증 재현 (T26820, 기존 5 run 재사용 가능)

```bash
cd FAB_BEAR/simulation
.venv/bin/python tools/stat_propagation_report.py \
  --runs-manifest out/validate_20260605/runs_manifest.csv \
  --g-star-file sample_csv/g_star_T26820.json \
  --t0 26820 --horizon 120 --n-runs 5 \
  --anchor-tg Diffusion_FE_120 \
  --out-dir out/validate_20260605 \
  --level L2 --alpha 0.05
```

기대: `candidate_rule=binom_L2`, 후보는 **이항 p<0.05** 인 G\* 밖·T0 비병목 TG만.
(N=5는 검정력이 약하므로 결과 해석은 N=30 권장 — 문서에 주석.)

---

*프롬프트 버전: 2026-06-05 · L2 default · L1 emerge demoted to reference tier*
