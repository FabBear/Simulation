# KPI CSV 4종 가이드

FabEnv 배치 시뮬이 생성하는 KPI CSV 4파일(`kpi_fab`, `kpi_process`, `kpi_toolgroup`, `kpi_tool`)의 스키마, 지표 정의, 적재 주기, DB 매핑, 해석 방법을 정리한 문서입니다.

**코드 SSOT:** `simulation/fab_env.py` (`_emit_*_kpis_*`, `_log_kpi_snapshot`)  
**DB 적재:** `simulation/load_csv_to_db.py` · [CSV_DB_MAPPING.md](CSV_DB_MAPPING.md)

---

## 목차

1. [한눈에 보기](#1-한눈에-보기)
2. [공통 CSV 스키마](#2-공통-csv-스키마)
3. [언제 행이 쌓이는가 (cadence)](#3-언제-행이-쌓이는가-cadence)
4. [파일별 KPI 카탈로그](#4-파일별-kpi-카탈로그)
5. [4파일 비교](#5-4파일-비교)
6. [행 수 추정](#6-행-수-추정)
7. [해석 가이드](#7-해석-가이드)
8. [주의사항](#8-주의사항)
9. [DB 검증 SQL](#9-db-검증-sql)

---

## 1. 한눈에 보기

| CSV 파일 | DB `level` | `scope` 예시 | KPI 개수 (종류) | 용도 |
|----------|------------|--------------|-----------------|------|
| `kpi_fab.csv` | FAB | `*` (전 fab) | 7 | fab 전체 납기·WIP·가동률 |
| `kpi_process.csv` | PROCESS | 공정명 (area) | 6 | 공정(Area) 단위 병목·OEE |
| `kpi_toolgroup.csv` | TOOLGROUP | toolgroup명 | 6 | 장비군 가용·대기 |
| `kpi_tool.csv` | TOOL | tool_id | 9 | 개별 장비 상태·OEE |

- 4파일 모두 **동일 컬럼** long-format.
- CSV에는 `level` 컬럼이 없고, **파일명**으로 DB `level`을 결정합니다.
- 런타임에는 FabEnv가 DB `kpi_snapshot` + CSV를 동시에 기록합니다.

```
FabEnv._kpi_snapshot_loop
    → _emit_all_kpis (cadence별)
        → _log_kpi_snapshot
            → DB bulk insert (level 포함)
            → kpi_{fab|process|toolgroup|tool}.csv append
```

---

## 2. 공통 CSV 스키마

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `run_id` | string | 에피소드 ID (`reset()` 시 12자 hex) |
| `snapshot_time` | float | 시뮬 시계(분) — 스냅샷 시각 |
| `scope` | string | 집계 범위 (FAB는 `"*"`) |
| `kpi_name` | string | 지표 이름 |
| `value` | float | 계산된 KPI 값 |
| `window_minutes` | int 또는 빈칸 | 윈도우 KPI만 값 있음 → DB `NULL` |
| `numerator` | float 또는 빈칸 | 재계산·감사용 분자 |
| `denominator` | float 또는 빈칸 | 재계산·감사용 분모 |
| `meta` | string 또는 빈칸 | JSON (OEE 분해, rtf 카운트 등) |

**DB 전용 컬럼:** `level` — `kpi_fab.csv` → `FAB`, `kpi_process.csv` → `PROCESS`, …

### Legacy 통합 파일

환경변수 `KPI_CSV_LEGACY_COMBINED=1` 이면 `kpi_snapshot.csv` 한 파일에 4레벨이 합쳐지며, 이때는 CSV에 **`level` 컬럼이 포함**됩니다.

---

## 3. 언제 행이 쌓이는가 (cadence)

SimPy 프로세스 `_kpi_snapshot_loop`가 주기적으로 `_emit_all_kpis()`를 호출합니다.  
**t=0 스냅샷은 없습니다** (초기 utilization 0 행 제거).

### 환경변수 (기본값)

| 변수 | 기본 | 역할 |
|------|------|------|
| `KPI_INSTANT_PERIOD_MIN` | 60 | 순간 KPI emit 주기 |
| `KPI_UTIL_WINDOW_MIN` | 60 | utilization·OEE 윈도우 |
| `KPI_TAT_WINDOW_MIN` | 60 | TAT 윈도우 (FAB만) |
| `KPI_THROUGHPUT_WINDOW_MIN` | 1440 | throughput 윈도우 (FAB만) |

### cadence별 emit 대상

| cadence due 시 | emit 내용 |
|----------------|-----------|
| `instant_p` (60분) | 4레벨 **순간 KPI** 전부 |
| `util_w` (60분) | FAB/PROCESS/TOOLGROUP/TOOL **윈도우 util·OEE** |
| `tat_w` (60분) | FAB `tat_min`만 |
| `tput_w` (1440분) | FAB `throughput_24h`만 |

### 타임라인 예 (기본 env, T=0~500분)

| snapshot_time | 추가되는 KPI (요약) |
|---------------|---------------------|
| 60 | instant 4레벨 + util + tat + throughput(최초 1회) |
| 120, 180, … | instant + util + tat (60분마다) |
| 1440 | throughput 추가 (시뮬이 충분히 길 때) |

> **같은 `snapshot_time`에 4파일 모두 행이 쌓입니다.** instant cadence가 due일 때 FAB·PROCESS·TOOLGROUP·TOOL 순간 KPI가 동시에 기록됩니다.

---

## 4. 파일별 KPI 카탈로그

### 4.1 `kpi_fab.csv` — FAB 전체

| kpi_name | 유형 | window | 수식 / 의미 | numerator | denominator |
|----------|------|--------|-------------|-----------|-------------|
| `rtf` | 순간 | — | **납기 준수율**: `due_date ≤ t_now` lot 중 on-time 완료 비율 | on_time | due_due |
| `completion_rate` | 순간 | — | **누적 완료율**: 완료 lot / 릴리즈 lot | finished | released |
| `q_time_min` | 순간 | — | 전 fab queue **평균 대기(분)** | Σ 대기시간 | waiting 수 |
| `wip` | 순간 | — | 전 fab WIP (대기+가공 중) | waiting | processing |
| `utilization` | 윈도우 | 60 | 전 tool RUN 시간 / (window × tool 수) | RUN 합 | window × N_tool |
| `tat_min` | 윈도우 | 60 | 윈도우 내 완료 lot **평균 TAT** | TAT 합 | 완료 수 |
| `throughput_24h` | 윈도우 | 1440 | 윈도우 내 **완료 lot 수** | count | — |

#### rtf vs completion_rate

| | `rtf` | `completion_rate` |
|--|-------|-------------------|
| 분모 | **납기가 이미 도래한** lot (`due_date ≤ t_now`) | **릴리즈된 전체** lot |
| 분자 | 그 중 on-time 완료 (`finish ≤ due`) | route 완료 lot |
| 용도 | 납기 준수 모니터링 | fab 진행률 |

#### 실데이터 예 (t=60)

```csv
rtf,0.0,,0.0,7.0          # due 도래 7 lot, on-time 0 → value=0 정상
wip,5.0,,0.0,5.0          # waiting=0, processing=5
utilization,0.0,60,0.0,92100.0   # 92100 = 60분 × 1535 tools
```

- `rtf` 초반: `value=0`, `denominator`만 증가 → **정상** (due는 쌓이나 아직 on-time 완료 없음).
- `wip`의 numerator/denominator는 KPI 값이 아니라 **대기 vs 가공 중 breakdown**.

---

### 4.2 `kpi_process.csv` — 공정(Area) 단위

| kpi_name | 유형 | window | 수식 / 의미 |
|----------|------|--------|-------------|
| `q_time_min` | 순간 | — | 해당 process 소속 tool queue 평균 대기 |
| `wip` | 순간 | — | process 내 waiting + processing |
| `utilization` | 윈도우 | 60 | process 소속 tool RUN / (window × tool 수) |
| `performance` | 윈도우 | 60 | Σ standard_proc_time / Σ actual_proc_time |
| `quality` | 윈도우 | 60 | (finish − rework − scrap) / finish, [0,1] |
| `oee_estimate` | 윈도우 | 60 | utilization × min(performance, 1) × quality |

#### scope가 무엇인가

- `scope` = **process bucket 이름** (`_process_tools`의 키).
- route step의 `area`를 toolgroup별로 집계한 뒤, 가장 많이 쓰인 area가 process명이 됩니다.
- `simulation_log.step_name`과 1:1이 **아닙니다**. 같은 area를 쓰는 여러 step이 한 process로 묶입니다.

#### 데이터 기록 시점

| 이벤트 | 기록 함수 |
|--------|-----------|
| step 완료 | `_kpi_record_step_finish(proc, t, actual, standard)` |
| rework | `_kpi_record_rework` |
| scrap (CQT 등) | `_kpi_record_scrap` |

- `standard` = `_compute_standard_proc_time(step, wafers_per_lot)`
- process는 `_kpi_resolve_process(tool_id, tool_group)`으로 결정

#### tool 매핑 없을 때

`proc_keys = _process_tools.keys() ∪ _kpi_proc_finish_dq.keys()`  
→ tool이 없어도 finish 이력이 있으면 **performance/quality/oee는 emit**. utilization은 소속 tool이 있을 때만.

---

### 4.3 `kpi_toolgroup.csv` — 장비군 단위

| kpi_name | 유형 | window | 수식 / 의미 |
|----------|------|--------|-------------|
| `available_tool_ratio` | 순간 | — | op_state ∈ {IDLE,RUN,SETUP} tool 수 / 그룹 tool 수 |
| `wip` | 순간 | — | 그룹 내 waiting + processing |
| `q_time_min` | 순간 | — | 그룹 queue 평균 대기(분) |
| `wait_ratio` | 순간 | — | waiting / max(1, 가용 tool 수) |
| `utilization_avg` | 윈도우 | 60 | unit별 RUN/window 비율의 **산술평균** |
| `setup_ratio_avg` | 윈도우 | 60 | unit별 SETUP/window 비율의 **산술평균** |

#### FAB utilization과의 차이

| | FAB `utilization` | TOOLGROUP `available_tool_ratio` |
|--|-------------------|----------------------------------|
| 측정 | **시간** 가동 (RUN 분 / window) | **스냅샷** 가용 장비 **대수** 비율 |
| 집계 | 전 fab tool 합산 | 그룹 내 tool |

> `utilization_avg`는 unit별 비율의 평균이므로, FAB utilization과 **직접 비교·합산하면 안 됩니다** (avg-of-avgs).

---

### 4.4 `kpi_tool.csv` — 개별 장비

| kpi_name | 유형 | window | 수식 / 의미 |
|----------|------|--------|-------------|
| `q_len` | 순간 | — | queue 길이 (건수) |
| `processing_count` | 순간 | — | 동시 가공 lot 수 (`resource.count`) |
| `avg_q_time` | 순간 | — | 해당 tool queue 평균 대기(분) |
| `utilization` | 윈도우 | 60 | RUN / window |
| `setup_ratio` | 윈도우 | 60 | SETUP / window |
| `down_ratio` | 윈도우 | 60 | (DOWN_PM + DOWN_BM) / window |
| `performance` | 윈도우 | 60 | Σstd / Σactual |
| `quality` | 윈도우 | 60 | (finish − rework − scrap) / finish |
| `oee_estimate` | 윈도우 | 60 | util × min(perf, 1) × quality |

#### PROCESS OEE vs TOOL OEE

수식은 **동일**합니다. scope와 내부 deque(`_kpi_proc_*` vs `_kpi_tool_*`)만 다릅니다.

#### 대기 시간 KPI 이름 차이

| KPI | 레벨 | 의미 |
|-----|------|------|
| `q_time_min` | FAB / PROCESS / TOOLGROUP | scope 전체 queue 평균 대기 |
| `avg_q_time` | TOOL | **한 tool** queue 평균 대기 |
| `q_len` | TOOL | queue **건수** (시간 아님) |

---

## 5. 4파일 비교

| 질문 | 답 |
|------|-----|
| 같은 시각에 4파일 모두 쌓이나? | **예** — instant/util cadence due 시 동일 `snapshot_time` |
| `q_time_min` / `wip`가 여러 파일에 있는 이유? | **동일 정의**, scope만 FAB → process → toolgroup으로 좁혀짐 |
| OEE는 어디에만? | **PROCESS, TOOL** — finish/standard/rework/scrap + utilization 조합 필요 |
| `window_minutes` 빈칸 vs 60 vs 1440? | 순간=빈칸, util/OEE=60, FAB throughput=1440 (env로 변경 가능) |

### instant 1회당 대략 행 수 (1535 tool, 106 toolgroup, 12 process 기준)

| 파일 | 계산 | 행 수 |
|------|------|-------|
| kpi_fab | ~7 KPI | ~7 |
| kpi_process | 12 × 6 | ~72 |
| kpi_toolgroup | 106 × 6 | ~636 |
| kpi_tool | 1535 × 9 | ~13,815 |
| **합계** | | **~14,500 / snapshot** |

---

## 6. 행 수 추정

짧은 검증 run (`sim_csv_kpi_check`, T≈780분, cadence 60분):

| 파일 | 실측 행 수 | 검증 |
|------|-----------|------|
| kpi_fab | 67 | 13 snapshot × ~5 KPI |
| kpi_process | 937 | 13 × 12 process × 6 |
| kpi_toolgroup | 8,269 | 13 × 106 × 6 |
| kpi_tool | 179,596 | 13 × 1535 × 9 |

### 추정식

```
rows_tool     ≈ (T / T_inst) × N_tool × (K_inst + K_util)
              ≈ (T / 60) × 1535 × (3 + 6)

rows_process  ≈ (T / T_inst) × N_process × 6
rows_toolgroup≈ (T / T_inst) × N_toolgroup × 6
rows_fab      ≈ (T / T_inst) × (4~5 instant) + (T / T_util) + (T / T_tat) + (T / T_tput)
```

- `K_inst` = 3 (`q_len`, `processing_count`, `avg_q_time`)
- `K_util` = 6 (`utilization`, `setup_ratio`, `down_ratio`, `performance`, `quality`, `oee_estimate`)

**장기 시뮬** (수만 분 × 1500+ tool)에서는 `kpi_tool.csv`가 **수백만~수천만 행**, GB 단위가 될 수 있습니다. DB 적재 전 용량을 반드시 확인하세요.

---

## 7. 해석 가이드

FabGuard 대시보드·병목 분석 시 권장 drill-down 순서:

```
FAB (rtf, wip, utilization)
  → PROCESS (utilization, q_time_min, oee)
    → TOOLGROUP (wait_ratio, available_tool_ratio)
      → TOOL (down_ratio, setup_ratio, oee meta)
```

| 관찰 | 해석 |
|------|------|
| FAB `rtf`↓ + `wip`↑ | 납기 도래 lot 대비 지연. `completion_rate`와 혼동 금지 |
| PROCESS `utilization`↓ + `q_time_min`↑ | 해당 공정(area) 병목 후보 |
| TOOLGROUP `wait_ratio`↑ | 가용 tool 대비 대기 과다 |
| TOOLGROUP `available_tool_ratio`↓ | 장비 down/부족 |
| TOOL `down_ratio`·`setup_ratio` | 개별 장비 상태 이슈 |
| TOOL `oee_estimate` meta | availability vs performance vs quality 분해 |

윈도우 KPI는 snapshot 시점 기준 **과거 N분 롤링** 값입니다. 시계열 분석 시 `snapshot_time`을 x축으로 사용하세요.

---

## 8. 주의사항

| 항목 | 설명 |
|------|------|
| avg-of-avgs | TOOLGROUP `utilization_avg` ≠ FAB utilization. 직접 비교·합산 금지 |
| window 경계 | state history·finish deque는 최대 window(`_kpi_max_window`)로 trim |
| rtf vs completion_rate | rtf = 납기 준수, completion_rate = 누적 완료율 |
| kpi_tool 용량 | 행 수 ∝ 시뮬 시간 × tool 수. 장기 run은 partition·샘플링 검토 |
| 구버전 CSV | `completion_rate` 없는 파일 = 구 run (코드 추가 이전) |
| throughput | 시뮬 길이 < `KPI_THROUGHPUT_WINDOW_MIN`이면 초기 1회만 또는 0 근처 |

---

## 9. DB 검증 SQL

CSV 적재 후:

```sql
SELECT level, kpi_name,
       COUNT(*) AS n,
       MIN(snapshot_time) AS t_min,
       MAX(snapshot_time) AS t_max
FROM kpi_snapshot
WHERE run_id = '<your_run_id>'
GROUP BY level, kpi_name
ORDER BY 1, 2;
```

특정 시각 FAB KPI만:

```sql
SELECT kpi_name, value, numerator, denominator, window_minutes, meta
FROM kpi_snapshot
WHERE run_id = '<your_run_id>'
  AND level = 'FAB'
  AND snapshot_time = 60
ORDER BY kpi_name;
```

---

## 관련 문서

- [CSV_DB_MAPPING.md](CSV_DB_MAPPING.md) — CSV 7종 ↔ DB 테이블 매핑
- [README_DOCKER.md](README_DOCKER.md) — Docker·환경변수·실행
- `simulation/fab_env.py` — KPI 계산 구현
