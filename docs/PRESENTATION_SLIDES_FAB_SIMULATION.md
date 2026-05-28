# FabGuard PoC — 시뮬레이션·CSV·데이터분석 발표 슬라이드 완성본

| 항목 | 내용 |
|------|------|
| 권장 제목 | **FabGuard PoC: 시뮬레이션 기반 병목 데이터셋과 Rule+ML 이중 알람** |
| 슬라이드 수 | 12장 |
| 대상 | SKALA 3기 2팀 / FabGuard PoC 이해관계자 |
| SSOT | `fab_env.py`, `run_sim_csv_once.py`, `data_labeling.ipynb`, `REPORT_SIMULATION_KPI.md` |

> PPT 제작 시: 각 슬라이드의 **【제목】** → 제목 상자, **【본문】** → bullet, **【발표 멘트】** → 스피커 노트

---

## Slide 01 — 표지

### 【제목】
FabGuard PoC  
시뮬레이션 · 스케줄링 CSV · 병목 데이터 분석

### 【본문】
- 발표 목적: FAB 시뮬레이션으로 **병목 데이터셋**을 만들고, **Rule + ML** 이중 알람 체계를 설계
- 범위: Cold start 시뮬 → CSV 7종 → Feature/Labeling → XGBoost PoC
- 핵심 메시지: *“랜덤 배정이 아닌 규칙 기반 시뮬에서 나온 데이터로, 설명 가능한 Rule과 보조 ML을 함께 쓴다”*

### 【발표 멘트】 (약 30초)
“오늘은 FabGuard PoC에서 시뮬레이션 엔진이 어떤 데이터로 돌아가고, 어떤 CSV가 나오며, 그 데이터로 병목 분석과 ML을 어떻게 연결했는지 공유합니다. 최종 목표는 ML만 믿지 않고, Rule 기반 라벨과 ML 예측을 함께 보는 운영 구조입니다.”

---

## Slide 02 — 프로젝트 목표와 발표 범위

### 【제목】
왜 시뮬레이션 데이터인가?

### 【본문】
| 구분 | 내용 |
|------|------|
| **문제** | 실 FAB MES만으로는 “미래 병목” 학습·검증 데이터 부족 |
| **해결** | SMT 기반 마스터 → SimPy FabEnv → **합성 시계열 CSV** |
| **PoC 산출** | Raw 로그 3종 + KPI 4종 + TG 단위 분석 테이블 |
| **운영 방향** | **Rule 알람(설명 가능)** + **ML 알람(조기 탐지, 보수적 threshold)** |

**오늘 다루지 않는 것 (범위 밖)**  
- 프론트 Digital Twin UI, K8s 운영, PPO 실운영 dispatch

### 【발표 멘트】 (약 40초)
“실제 공장 데이터만으로는 ‘앞으로 막힐 TG’를 라벨링하고 검증하기 어렵습니다. 그래서 SMT 마스터를 넣은 시뮬레이션으로 대량 시계열을 만들고, KPI와 이벤트 로그를 분리해 저장합니다. PoC의 운영 철학은 ML 단독이 아니라 Rule과 ML을 동시에 보는 이중 알람입니다.”

### 【Q&A 포인트】
- Q: 실데이터 대체 가능? → A: PoC는 시뮬 합성 데이터, 실데이터는 calibration/검증 단계에서 연결.

---

## Slide 03 — 시뮬레이션 입력 데이터셋

### 【제목】
시뮬레이션은 무엇을 입력으로 받는가?

### 【본문】
**입력 소스**
- `simulation/data/SMT_3_*.xlsx` (Route, ToolGroup, Setups, PM, Lotrelease, Transport 등)
- `init_db.py` → PostgreSQL ORM 마스터 적재

**엔진 핵심**
- `fab_env.py` (SimPy FabEnv)
- Lot 단위로 Route step 순회, Tool queue·가공·KPI 기록

**실행 모드**
| 모드 | 설명 |
|------|------|
| **Cold start** | 0분부터 마스터 lot release로 전체 Fab 가동 |
| **FORWARD** (참고) | MES T0 스냅샷 + 계획 release (별도 runner) |

### 【시각자료】
- 박스 다이어그램: `XLSX → init_db → Postgres → FabEnv → CSV/DB`

### 【발표 멘트】 (약 45초)
“시뮬의 입력은 엑셀 마스터입니다. 공정 route, 장비군, setup, PM/BM, lot release 스케줄이 DB에 올라가고 FabEnv가 이를 읽어 Lot 흐름을 재현합니다. 우리 PoC의 메인 경로는 cold start로, fab 전체를 처음부터 돌려 CSV를 뽑는 방식입니다.”

### 【근거】
- `FAB_BEAR/simulation/init_db.py`, `fab_env.py`, `README.md`

---

## Slide 04 — Lot 생애주기 (Release → 완료)

### 【제목】
Lot 한 건은 시뮬 안에서 어떻게 흐르는가?

### 【본문】
**1. Release**  
- 마스터 `lot_release` 스케줄에 따라 Lot 투입  
- `start_date`, `due_date` 부여 (상대 시뮬 시계 기준)

**2. Step 진입**  
- Route의 다음 step으로 이동  
- 해당 step의 Tool Group 후보 확정

**3. Queue & Dispatch**  
- **Tool별 PriorityResource queue** (TG 공유 1개 queue가 아님)  
- Dispatch: **Critical Ratio** 등 rule 기반 (기본 `DISPATCH_MODE=rule`)  
- Tool 선택: LTL lock → setup avoidance → wakeup ranking

**4. Process**  
- Setup(필요 시) → RUN → step 완료  
- `standard` vs `actual` process time 기록

**5. 완료 / 예외**  
- Route 종료, rework/scrap(CQT 등), PM/BM DOWN 반영

### 【시각자료】
```
Release → Step → [후보 Tool] → Queue → Setup/RUN → 완료 → 다음 Step
```

### 【발표 멘트】 (약 50초)
“Lot는 release로 들어오고 step마다 장비군 후보를 찾습니다. 중요한 점은 queue가 tool 단위라는 것과, dispatch가 랜덤이 아니라 critical ratio 같은 규칙으로 동작한다는 점입니다. 가공이 끝나면 다음 step으로 가고, PM이나 breakdown이 있으면 가용 장비가 줄어들며 대기가 늘어납니다.”

### 【근거】
- `fab_env.py`: `_lot_process`, `_choose_tool_for_lot`, `_critical_ratio`

### 【Q&A 포인트】
- Q: 장비 배정이 랜덤? → A: **아니요**, rule + wakeup/setup/LTL 제약.

---

## Slide 05 — 공정 규칙 & Due date · 공정시간

### 【제목】
공정마다 다른 제약: Setup, PM/BM, CQT, LTL

### 【본문】
| 규칙 | 역할 | 병목에 미치는 영향 |
|------|------|-------------------|
| **Setup** | recipe/가스 변경 시 setup 시간 | 가용 시간 감소, queue 증가 |
| **PM / BM** | 예방정비·고장 DOWN | `available_tool_ratio` 하락 |
| **CQT** | 구간 시간/품질 타이머 | scrap/rework로 흐름 왜곡 |
| **LTL** | 특정 step 이후 1대 lock | hot-spot·쏠림 강화 |
| **Transport/Loading** | 이동·로딩 시간 | step 간 지연 |

**Due date**
- Release 시점 기준 due 부여  
- PoC RTF: **납기 준수율** (`on_time / due_due`) — 누적 완료율과 분리

**공정 시간**
- Standard: step·wafer 기준 이론 시간  
- Actual: 시뮬에서 실제 소요 (setup/down 포함)

### 【발표 멘트】 (약 45초)
“공정마다 setup, PM, CQT, LTL이 다르게 적용됩니다. 이 제약들이 겹치면 특정 TG만 가용 장비가 줄고 queue가 쌓입니다. due date는 release 때 정해지고, KPI의 RTF는 납기 준수를 봅니다. 공정 시간은 standard와 actual을 따로 기록해 performance 지표에도 쓰입니다.”

### 【근거】
- `docs/SMT2020_SIM_PATCHES.md`, `docs/KPI_CSV_4FILES.md`

---

## Slide 06 — 병목이 후반에 많아지는 구조

### 【제목】
장기 시뮬레이션에서 “후반 병목 편향”이 생기는 이유

### 【본문】
**관측 (장기 run `3e11c2ef42da`, TG×t 약 539K행)**  
| KPI | median | 95% | max | zeros% |
|-----|--------|-----|-----|--------|
| q_time_min | 0 | 255분 | **43,433분** | 90% |
| wait_ratio | 0 | 1.0 | **5,674** | 90% |
| wip | 1 | 24 | **6,032** | 36% |

**구조적 원인**
1. Lot/WIP 누적 → 후반 queue 압력 증가  
2. PM/BM·setup으로 가용 tool 감소  
3. 특정 TG hot-spot (TG avg util 낮아도 unit max util 높음)

**분석 시 주의**
- 시간 인덱스(`snapshot_time`)를 feature로 넣으면 **가짜 고성능**  
- → feature에서 제외, **시간순 train/val/test** 필요

### 【시각자료】
- 막대/라인: 초반·중반·후반 `y_bottleneck` 비율 비교 (노트북에서 생성 가능)

### 【발표 멘트】 (약 50초)
“장기 run을 보면 KPI의 90%가 0에 가깝고, tail만 극단적으로 큽니다. 이건 시뮬이 틀렸다기보다 backlog가 누적되는 구조 때문입니다. 그래서 ML에서 snapshot_time을 빼고, 랜덤 split 대신 시간순 split을 씁니다.”

---

## Slide 07 — 스케줄링 시뮬 실행 절차 (4단계)

### 【제목】
CSV는 이렇게 뽑는다: 준비 → 실행 → 산출 → 검증

### 【본문】
| 단계 | 작업 | 체크 |
|------|------|------|
| **1. 준비** | `docker compose up -d db`, `init_db.py`, venv | DB host/port, 마스터 적재 |
| **2. 실행** | `run_sim_csv_once.py` | `DISPATCH_MODE=rule` |
| **3. 산출** | `SIM_CSV_DIR` 아래 CSV 7종 | `run_id` 확인 |
| **4. 검증** | 행 수, `snapshot_time` min/max | KPI 종류 수 일치 |

**실행 예시**
```bash
export SIM_CSV_DIR=./sim_csv_out
export SIM_END_MINUTES=2000        # short: 검증
export KPI_INSTANT_PERIOD_MIN=60
.venv/bin/python run_sim_csv_once.py \
  --csv-dir ./sim_csv_out --end-minutes 2000 --max-steps 500
```

**장기 vs 단기 run**
| | Short | Long (PoC SSOT) |
|---|-------|------------------|
| 목적 | 파이프라인 검증 | 병목 패턴·ML 데이터 |
| 예시 | ~4,740분 | **60 ~ 305,160분** |
| run_id | `48a57f5fd08d` 등 | **`3e11c2ef42da`** |

### 【발표 멘트】 (약 50초)
“실행은 네 단계로 고정합니다. DB와 마스터 준비 후 run_sim_csv_once를 돌리면 run_id가 붙은 CSV 7종이 나옵니다. 검증에서 snapshot_time 범위와 행 수를 꼭 확인합니다. short run은 빠른 테스트, long run은 병목 tail과 ML용입니다.”

### 【근거】
- `run_sim_csv_once.py`, `README.md`

---

## Slide 08 — 산출 CSV 7종 개요

### 【제목】
Raw 로그 3종 vs KPI 4종 — 역할을 섞지 말 것

### 【본문】
| # | 파일 | 한 행의 의미 | 용도 |
|---|------|-------------|------|
| 1 | `simulation_process.csv` | Lot·step 완료 1건 | TAT/처리 이력 |
| 2 | `lot_events.csv` | Lot 이벤트 1건 | 상태 추적 |
| 3 | `tool_state.csv` | Tool/TG 상태 변화 | DOWN/SETUP 타임라인 |
| 4 | `kpi_fab.csv` | FAB×시각×KPI | Fab 전체 RTF/WIP |
| 5 | `kpi_process.csv` | Process×시각×KPI | Area 병목 |
| 6 | `kpi_toolgroup.csv` | **TG×시각×KPI** | **병목 ML 1차 입력** |
| 7 | `kpi_tool.csv` | Tool×시각×KPI | unit hot-spot 집계 |

**장기 run 실측 (참고)**
- 총 데이터 행 ~**8,467만**, `kpi_tool` ~**5.2GB**
- `kpi_tool` 행 수 = 5,086 snap × 1,535 tools × 9 KPI

### 【발표 멘트】 (약 45초)
“CSV는 이벤트 3종과 KPI 4종입니다. 원인 분석은 Raw, 알람과 집계는 KPI입니다. 병목 PoC의 중심은 kpi_toolgroup이고, kpi_tool은 max 집계로 hot-spot을 보완합니다.”

### 【근거】
- `KPI_CSV_4FILES.md`, `CSV_DB_MAPPING.md`

---

## Slide 09 — CSV 컬럼 해석 (실무 관점)

### 【제목】
핵심 컬럼만 정확히 이해하기

### 【본문】
**KPI 공통 (long format)**  
`run_id`, `snapshot_time`, `scope`, `kpi_name`, `value`, `window_minutes`

**TG KPI (`scope` = toolgroup명)** — 병목 feature 핵심
| kpi_name | 의미 | 해석 팁 |
|----------|------|---------|
| `q_time_min` | TG queue 평균 대기(분) | ↑ 지속 시 적체 |
| `wait_ratio` | 대기 lot / 가용 tool | **>1** 이면 가용 tool로 1회전해도 대기 잔존 |
| `wip` | 대기+가공 lot 수 | 부하량 |
| `available_tool_ratio` | 가용 tool 비율 | ↓ PM/BM 영향 |
| `utilization_avg` | unit util 평균 | avg-of-avgs 주의 |
| `setup_ratio_avg` | setup 비율 평균 | recipe churn |

**Tool KPI → 집계 feature**
| 원본 | 집계 | 의미 |
|------|------|------|
| `utilization` | `max_util` | TG 내 최고 부하 unit |
| `avg_q_time` | `max_avg_q_time` | TG 내 최악 대기 tool |

### 【발표 멘트】 (약 50초)
“KPI는 long format입니다. TG의 wait_ratio가 1을 넘으면 병목 신호로 타당합니다. 다만 장기 run tail이 크기 때문에 단일 임계값만으로는 부족하고, max_util 같은 tool 집계를 같이 봅니다.”

---

## Slide 10 — Feature · Labeling 파이프라인

### 【제목】
TG KPI + Tool KPI → Feature → Label

### 【본문】
**Feature 구성 (시각 t)**
1. `kpi_toolgroup.csv` pivot → wide  
2. `kpi_tool.csv` chunk → **max** (`max_util`, `max_avg_q_time`, `max_q_len`)  
3. merge on `(snapshot_time, toolgroup)`  
4. ML 입력: 위 KPI + `toolgroup_enc` (**`snapshot_time` 제외**)

**라벨 2종**
| 라벨 | 기준 | 용도 |
|------|------|------|
| `y_bottleneck` | REPORT 부등식 @ **t+H** (H=120분) | **XGBoost 타깃 (SSOT)** |
| `y_bottleneck_pct` | 분위수 tail @ **t** | EDA·임계값 탐색 |

**REPORT 라벨 (요약)** — `t+H` 시점 KPI에 적용
```
y=1 if (q≥Q and (w≥W or wip≥N)) or avail≤A
      or (max_util≥U_hi and util_avg<U_lo)
      or (max_q≥Q and w≥W)
```
- 기본 상수: Q=30, W=1, N=3, A=0.5, U_hi=0.8, U_lo=0.5  
- 노트북: §6 분위수 → §7 임계값 **자동 매핑** 옵션 (`AUTO_THR_FROM_PCT`)

**장기 run 라벨 분포 (참고)**  
`y_bottleneck` positive ≈ **37.9%** (538,904행)

### 【시각자료】
```
TG long + Tool long → wide → t+H merge → y_bottleneck → XGBoost
```

### 【발표 멘트】 (약 55초)
“분석 단위는 Tool Group입니다. feature는 t 시점 KPI이고, 라벨은 t+120분 KPI로 REPORT 규칙을 적용한 y_bottleneck입니다. 분위수 라벨은 분포 탐색용이고, 학습에는 y_bottleneck만 씁니다.”

### 【근거】
- `build_bottleneck_labels.py`, `data_labeling.ipynb` §6–§7

---

## Slide 11 — 데이터 분할 · ML · Threshold 운영

### 【제목】
누수 방어 후 XGBoost — Rule과 함께 쓰는 ML

### 【본문】
**데이터 분할 (현재 PoC)**
| 방식 | 설명 |
|------|------|
| ❌ Random 70/15/15 | 미래 정보 leakage 위험 |
| ✅ **시간순 split** | `snapshot_time` 고유값 기준 앞 70% / 중 15% / 뒤 15% |

**모델**
- `XGBClassifier`, pooled TG 모델 + `LabelEncoder(toolgroup)`
- `scale_pos_weight`로 클래스 불균형 보정

**Threshold (운영)**
- `pred = (proba >= threshold)`  
- threshold **↑** → 알람 ↓ (둔감, Precision↑)  
- PoC 제안: Rule 알람 유지 + ML은 **0.6~0.8**에서 validation으로 고정

**이중 알람 전략**
| | Rule | ML |
|---|------|-----|
| 강점 | 설명 가능, 기준 고정 | 비선형 패턴, 조기 신호 |
| 약점 | 둔한 경우 있음 | calibration·편향 주의 |
| 운영 | 1차 확정 기준 | 보조/조기 경보 |

### 【시각자료】
- Test `proba` vs `snapshot_time` scatter (노트북 §8 추가 셀)
- Threshold 0.5 / 0.6 / 0.7 알람 수 비교 표

### 【발표 멘트】 (약 55초)
“ML 고도화는 다음 단계로 미루고, 지금은 파이프라인과 운영 원칙이 핵심입니다. random split은 쓰지 않고 시간순으로 나눕니다. 운영에서는 Rule 알람을 기준으로 두고, ML은 threshold를 올려 보수적으로 씁니다.”

### 【Q&A 포인트】
- Q: proba 0.6 올리면 더 좋은가? → A: 알람이 줄어듦. 목표 precision/시간당 알람 수로 맞춤.

---

## Slide 12 — 결론 & 다음 단계

### 【제목】
정리: 우리가 만든 것 / 리스크 / Next

### 【본문】
**✅ 확보한 것**
- Rule 기반 Fab 시뮬 + **CSV 7종** 표준 파이프라인  
- TG 단위 Feature/Label (`y_bottleneck`)  
- Leakage 방어: `snapshot_time` 제외, 시간순 split  
- Rule + ML 이중 알람 운영안

**⚠️ 리스크**
- 단일 장기 run → 일반화 한계  
- KPI tail 극단값 (`wait_ratio` 수천) → clip/log 검토  
- §6 분위수: train-only ref 미적용 시 label leakage

**▶ Next (ML 고도화 전)**
1. PPT용 그래프 고정 (시간별 y rate, proba, threshold sweep)  
2. `build_bottleneck_labels.py`와 노트북 **H=60/120 통일**  
3. Rule 알람 vs ML 알람 **동시 발생 리포트** 샘플  
4. (선택) multi-run 수집 후 run-block CV

### 【발표 멘트】 (약 40초)
“정리하면, 시뮬에서 CSV를 만들고, TG KPI와 Tool 집계로 feature를 만들며, REPORT 규칙으로 라벨을 붙였습니다. ML은 보조 채널로 두고 Rule과 함께 보는 구조입니다. 다음은 그래프를 발표용으로 고정하고, 라벨 horizon과 threshold 정책을 문서화하는 단계입니다.”

---

## 부록 A — 슬라이드별 제작 체크리스트

| Slide | 필수 그림/표 |
|-------|----------------|
| 03 | 입력→DB→엔진 플로우 |
| 04 | Lot 생애주기 플로우 |
| 06 | KPI describe 표 또는 tail 히스토그램 |
| 07 | 4단계 실행 표 |
| 08 | CSV 7종 표 |
| 10 | feature→label 파이프라인 |
| 11 | time split vs random 개념도 + threshold 표 |

---

## 부록 B — 예상 Q&A 10선 (발표자용 한 줄 답)

1. **랜덤 배정?** → Rule dispatch, wakeup/setup/LTL 반영.  
2. **왜 시뮬?** → 미래 병목 라벨·대량 시계열 확보.  
3. **Raw vs KPI?** → Raw=원인, KPI=알람/집계.  
4. **TG vs Tool KPI?** → TG 평균 + Tool max로 hot-spot 보완.  
5. **양성률 높으면 좋음?** → 아님, 운영 비용 기준 threshold 조정.  
6. **wait_ratio>1 의미?** → 가용 tool 1바퀴로도 대기 해소 안 됨.  
7. **왜 snapshot_time 제외?** → 시간 누수 방지.  
8. **분위수 라벨 용도?** → 임계 탐색; 학습은 y_bottleneck.  
9. **ML만 쓰면?** → 설명성·신뢰 이슈, Rule 병행.  
10. **다음 우선순위?** → threshold 정책, H 통일, multi-run 검증.

---

## 부록 C — PPT 디자인 가이드 (간단)

- **색상**: Raw=회색, KPI=파랑, Label=주황, ML=보라  
- **한 슬라이드 bullet**: 최대 5개  
- **숫자 슬라이드**: Slide 06, 08, 10에만 밀도 높게  
- **데모 슬라이드**: Slide 11에 test proba 시간축 그래프 1장

---

*문서 생성: PPT 발표 원고 완성본 · FAB_BEAR PoC*
