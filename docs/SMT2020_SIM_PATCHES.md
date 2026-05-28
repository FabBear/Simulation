# SMT2020 FabEnv 정합성 패치 (P0~P5)

`fab_env.py` / `init_db.py` / `models.py` 변경 요약. 적용 후 **`init_db.py` 재실행** 필요 (`drop_all`).

## P0 — CQT 구간 타이머

| 항목 | 내용 |
|------|------|
| DB | `cqt_anchor_step` (행 STEP), `cqt_target_step` (STEP FOR CRITICAL QUEUE TIME) |
| 시작 | 앵커 스텝 n **FINISH 직후** → `CQT_START`, `deadline = now + CQT` |
| 종료 | 타겟 스텝 m **도착 시** (process 전) → `CQT_END` |
| 위반 | `now > deadline` & target 미도달 → `SCRAP` / `CQT_TIMEOUT` |

```
Step n FINISH ──► CQT_START ──► [queue+transport+loading] ──► Step m arrive ──► CQT_END
                      │________________ deadline ________________|
```

## P1 — PM counter + FOA

- Counter PM: `self._pm_piece_count[tool_id]` — FINISH 시 wafer 수 누적, `MTBeforePM` 도달 시 PM 후 리셋
- FOA: `stagger = foa_min * (tool_index / tool_count)` — tool별 첫 PM 시각 분산

## P2 — TOOL WAKE UP Ranking

- `tool_wakeup_ranking`: Least Setuptime / Shortest Queue / Idle First → `_choose_tool_for_lot` 정렬

## P3/P4 — DISPATCHING + Superhot 4b

- `dispatch_rule` 파싱: `Setupavoidance`, `Superhotlot`
- Superhot: queue에 superhot 있으면 **다음 dispatch**부터 superhot만 후보 (RUN 선점 없음)

## P5 — Lotrelease due (옵션 A)

- `RELEASE INTERVAL > 0` 시: `lot_due = calc_minutes(DUE DATE) + k * release_interval`
- `SMT_3_Lotrelease_Engineering.xlsx` — **import 제외** (8년 벤치마크, FabEnv 미사용)

## 제외

- `SMT_3_Setup_Matrix_Implant_Gas.xlsx`
- Superhot 4c (RUN 중단)
- `core/what_if_executor`

## 검증

```bash
cd simulation
.venv/bin/python init_db.py
.venv/bin/python -m pytest tests/ -q
.venv/bin/python run_sim_csv_once.py --csv-dir ./sim_csv_check_p0p5 --end-minutes 500
```
