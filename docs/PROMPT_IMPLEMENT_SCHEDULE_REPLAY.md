# Task: Schedule Tool-Path Replay 구현 (FORWARD baseline + WHAT-IF patch)

> **설계 SSOT:** [REPORT_SCHEDULE_REPLAY.md](./REPORT_SCHEDULE_REPLAY.md)  
> **선행 PoC:** [PROMPT_FORWARD_T0_FROM_SIM_CSV.md](./PROMPT_FORWARD_T0_FROM_SIM_CSV.md) — T0 bundle은 **재사용**, 수정 최소화

## 목적

Reference cold-start run(`run_id_ref`)의 **step별 Tool 배정**을 `schedule_tool_map`으로 추출하고,  
`run_sim_forward_once.py`가 **`DISPATCH_MODE=schedule_replay`** 로 H분 전개하여 ref run과 **경로·KPI**를 비교 가능하게 한다.  
WHAT-IF에서는 **schedule patch**로 Tool 재배치 대응안을 반영한다.

---

## 범위

| In scope | Out of scope |
|----------|--------------|
| `mes_schedule_step_tool` ETL + DB load | 절대 시각(ARRIVAL/FINISH) 리플레이 |
| `fab_env` `_choose_tool_for_lot` schedule pin | Queue 순서 schedule pin (2단계) |
| `compare_schedule_replay.py` | Bit-identical KPI |
| WHAT-IF schedule patch (1단계: row override) | `DISPATCH_RULE=FIFO` 신규 구현 |
| Smoke + E2E on `FWD_CSV_f5178_T620` scale | Cold-start `run_sim_csv_once` 동작 변경 |

---

## 전제 조건 (이미 있음)

- `tools/build_forward_scenario_from_csv.py`
- `load_mes_scenario.py` (4 core CSV, `--force-draft`, partial load guard)
- `run_sim_forward_once.py`, `fab_env.py` scenario inject
- Sample: `Simulation/SMT_2000_Simulation/sim_csv_kpi_check/` (`run_id=f5178b41645d`)
- Postgres `@ localhost:5433` (FAB_BEAR `.env`)

---

## Locked 결정 (변경 금지 unless bug)

| ID | 내용 |
|----|------|
| L1 | Map grain: `(scenario_id, lot_id, step_seq) → tool_id` — **시간 컬럼 없음** |
| L2 | Source: `simulation_process` > `lot_events`(RUN/FINISH) |
| L3 | Lots: T0 WIP (`step >= current_step_seq`) ∪ release plan `(T0,T0+H]` |
| L4 | `use_master_lot_release = false` |
| L5 | Inject order: tool → queue → wip → cqt → whatif → release |
| L6 | Hook: **`_choose_tool_for_lot` only**; default `DISPATCH_MODE=rule` |
| L7 | LTL lock **>** schedule map |

---

## Phase P0 — ETL: `build_schedule_tool_map.py`

**Create:** `FAB_BEAR/simulation/tools/build_schedule_tool_map.py`

### CLI

```bash
.venv/bin/python tools/build_schedule_tool_map.py \
  --run-id f5178b41645d \
  --t0 620 --horizon 120 \
  --scenario-id FWD_REPLAY_f5178_T620 \
  --sim-csv-dir /path/to/sim_csv_kpi_check \
  --wip-csv scenario_out/FWD_REPLAY_f5178_T620/mes_wip_snapshot.csv \
  --releases-csv scenario_out/FWD_REPLAY_f5178_T620/mes_lot_release_plan.csv \
  --out scenario_out/FWD_REPLAY_f5178_T620/mes_schedule_step_tool.csv
```

`--wip-csv` / `--releases-csv` 생략 시 `--sim-csv-dir`만으로 ACTIVE_LOTS 추정 가능하면 허용.

### 출력 CSV 컬럼

```
scenario_id,source_run_id,lot_id,route_id,step_seq,tool_id,tool_group,source,mes_row_hash
```

### 알고리즘

1. **ACTIVE_LOTS** = wip `lot_id` ∪ releases where `T0 < release_time <= T0+H`
2. **Primary:** `simulation_process.csv` chunked read  
   - `run_id`, `end_time > T0`, `start_time <= T0+H`, `lot_id in ACTIVE_LOTS`  
   - key `(lot_id, step_seq)` → `tool_id` (non-empty)
3. **Secondary:** `lot_events.csv` — `RUN`/`FINISH`, `event_time in (T0,T0+H]`, keys not in map
4. WIP lot: drop rows where `step_seq < wip.current_step_seq`
5. Write `build_schedule_confidence.json`: row counts, conflicts, lots without map

### Reuse

- `_iter_csv`, `_float`, lot_id parsing from `build_forward_scenario_from_csv.py` (import or small shared util — **do not duplicate 500 lines**)

---

## Phase P1 — DB schema + load

### P1a DDL

**Create:** `simulation/sql/flyway/V004__mes_schedule_step_tool.sql`

```sql
CREATE TABLE IF NOT EXISTS mes_schedule_step_tool (
  id BIGSERIAL PRIMARY KEY,
  scenario_id VARCHAR(64) NOT NULL REFERENCES mes_scenario(scenario_id) ON DELETE CASCADE,
  source_run_id VARCHAR(64),
  lot_id VARCHAR(128) NOT NULL,
  route_id VARCHAR(128),
  step_seq INTEGER NOT NULL,
  tool_id VARCHAR(128) NOT NULL,
  tool_group VARCHAR(128),
  source VARCHAR(32),
  mes_row_hash VARCHAR(64),
  UNIQUE (scenario_id, lot_id, step_seq)
);
CREATE INDEX IF NOT EXISTS ix_mes_schedule_step_tool_scenario
  ON mes_schedule_step_tool(scenario_id);
```

### P1b Model

**Edit:** `simulation/models.py` — add `MesScheduleStepTool` matching DDL.

### P1c Loader

**Edit:** `simulation/load_mes_scenario.py`

- Add `--schedule PATH`
- `_load_schedule(db, scenario_id, rows)`: delete-by-scenario then insert
- If `--schedule` omitted on full load: **do not** delete existing schedule rows (or document: full bundle should pass schedule when replay intended)
- Extend `_audit_fab_env_compat`: warn if `DISPATCH_MODE=schedule_replay` env set but 0 schedule rows (optional, log only)

---

## Phase P2 — Engine: `fab_env.py`

### P2a Env / state

In `FabEnv.__init__` / `reset()`:

```python
self._schedule_tool_map: dict[tuple[str, int], str] = {}  # (lot_id, step_seq) -> tool_id
self._schedule_tool_patch: dict[tuple[str, int], str] = {}  # WHAT-IF overrides
self._dispatch_mode = os.environ.get("DISPATCH_MODE", "rule").lower()
```

Load in `_apply_scenario_overrides` (after scenario known):

```python
if self._dispatch_mode == "schedule_replay":
    self._load_schedule_tool_map(db, scenario.scenario_id)
    if scenario.mode == "WHATIF":
        self._load_schedule_tool_patch(db, scenario.scenario_id)
```

### P2b Lookup helper

```python
def _scheduled_tool_for_step(self, lot_name: str, step_seq: int) -> str | None:
    key = (lot_name, int(step_seq))
    if key in self._schedule_tool_patch:
        return self._schedule_tool_patch[key]
    return self._schedule_tool_map.get(key)
```

### P2c Hook `_choose_tool_for_lot`

**After** `FORCE_TOOL` check, **before** wakeup ranking:

```python
if self._dispatch_mode == "schedule_replay":
    sched_tid = self._scheduled_tool_for_step(lot_name, int(step.step_seq))
    if sched_tid and sched_tid in candidate_ids:
        if self._allowed_by_setup_avoidance(self.tools[sched_tid], step.setup_id):
            return sched_tid
        # log validation_report: schedule tool setup blocked
    elif sched_tid:
        # log: schedule tool not in candidates (LTL?) -> fall through to rule
        pass
# existing rule path unchanged
```

**Do NOT** change cold-start path: no `scenario_id` → map empty, mode irrelevant.

### P2d WHAT-IF patch (P5 minimal in P2 if time)

Option A (preferred PoC): table `mes_schedule_step_tool_override`  
Option B: `mes_whatif_action` kind `SCHEDULE_TOOL_OVERRIDE` with `payload_json: {lot_id, step_seq, tool_id}`

Merge in `_load_schedule_tool_patch`.

---

## Phase P3 — Runner + pipeline script

### P3a `run_sim_forward_once.py`

- Document: set `DISPATCH_MODE=schedule_replay` for replay runs
- Optional CLI: `--dispatch-mode schedule_replay` → sets env before `FabEnv()`
- Default unchanged: `rule`

### P3b Pipeline script

**Create:** `simulation/tools/run_schedule_replay_pipeline.sh`

```bash
# 1 build_forward_scenario_from_csv
# 2 build_schedule_tool_map
# 3 load_mes_scenario (4 snapshots + releases + schedule)
# 4 promote_scenario_validated
# 5 DISPATCH_MODE=schedule_replay run_sim_forward_once
# 6 compare_schedule_replay
```

Parameters: `RUN_ID`, `T0`, `H`, `SCENARIO_ID`, `SIM_CSV_DIR`, `CSV_OUT_DIR`

---

## Phase P4 — Compare tool

**Create:** `simulation/tools/compare_schedule_replay.py`

### Input

- `--ref-run-id`, `--ref-csv-dir` (simulation_process + lot_events)
- `--replay-csv-dir` (replay run output)
- `--t0`, `--horizon`
- `--scenario-id` (optional, for schedule CSV cross-check)

### Output

`schedule_replay_report.json` + stdout summary:

| Field | Definition |
|-------|------------|
| `path_match_rate` | ref process steps in window where replay used same `tool_id` |
| `path_compared_steps` | count |
| `kpi_tg_at_t_end` | optional: bottleneck TG `q_time_min` ref vs replay @ T0+H |
| `release_count_ref` / `release_count_replay` | ARRIVAL in window |

---

## Phase P5 — WHAT-IF + tests

### Tests

**Create:** `simulation/tests/test_schedule_replay_smoke.py`

- Tiny in-memory or fixture CSV: 1 lot, 2 steps, map pins tool B
- Assert `_choose_tool_for_lot` returns B when mode=schedule_replay
- Assert mode=rule unchanged (regression)

**Keep green:** `tests/test_scenario_forward_smoke.py`

### WHAT-IF E2E

- Baseline scenario: replay, no patch
- Whatif scenario: `baseline_scenario_id` + 1 patch row → different tool at step X
- Run `compare_whatif.py` or extend compare tool

---

## Acceptance checklist (must pass before done)

### ETL

- [ ] `mes_schedule_step_tool.csv` row count > 0 for `f5178b41645d`, T0=620, H=120
- [ ] No WIP lot rows with `step_seq < current_step_seq`
- [ ] `build_schedule_confidence.json` written

### Load + run

- [ ] Full load: wip + tools + queues + releases + schedule
- [ ] `promote` → `VALIDATED`
- [ ] `DISPATCH_MODE=schedule_replay run_sim_forward_once` exit 0, status `DONE`

### Engine regression

- [ ] `DISPATCH_MODE` unset: cold-start / policy forward unchanged
- [ ] `test_scenario_forward_smoke.py` passes

### Compare

- [ ] `compare_schedule_replay.py` produces report with `path_match_rate`
- [ ] PoC: document actual rate in `docs/REPORT_SCHEDULE_REPLAY.md` § implementation results (append section)

### WHAT-IF (P5)

- [ ] Single patch changes replay tool at patched step

---

## 파일별 Do / Don't

| Do | Don't |
|----|-------|
| Feature-flag via `DISPATCH_MODE` | Rewrite `_lot_process` loop |
| Delete schedule rows on scenario reload with `--schedule` | Break `use_master_lot_release=false` |
| Log conflicts to `validation_report` | Require schedule for policy FORWARD |
| Chunk-read large CSVs | Load 5GB kpi_tool for schedule ETL |
| Match existing code style in `fab_env.py` | Add FIFO dispatch without tests |

---

## Agent copy-paste prompt (English)

```text
Implement Schedule Tool-Path Replay for FAB_BEAR per docs/PROMPT_IMPLEMENT_SCHEDULE_REPLAY.md.

Order: P0 build_schedule_tool_map.py → P1 V004 DDL + models + load_mes_scenario --schedule
→ P2 fab_env DISPATCH_MODE=schedule_replay hook in _choose_tool_for_lot
→ P3 run_sim_forward_once env/CLI + run_schedule_replay_pipeline.sh
→ P4 compare_schedule_replay.py → P5 tests + WHAT-IF patch.

Constraints:
- Map: (lot_id, step_seq) -> tool_id only; no absolute times.
- Primary source simulation_process; fallback lot_events RUN/FINISH.
- Active lots = T0 wip (future steps) + release plan in (T0, T0+H].
- use_master_lot_release=false; existing inject order unchanged.
- Default DISPATCH_MODE=rule; cold-start must not change.
- LTL lock beats schedule map; setup avoidance still applies.

Validate on run_id f5178b41645d, T0=620, H=120 after building forward bundle.
All acceptance checkboxes in PROMPT_IMPLEMENT_SCHEDULE_REPLAY.md must pass.
Update REPORT_SCHEDULE_REPLAY.md with implementation results when done.
```

---

## 참고 코드 위치

| File | Function / area |
|------|-----------------|
| `fab_env.py` | `_choose_tool_for_lot` (~1670), `_apply_scenario_overrides` (~920) |
| `fab_env.py` | `_LotReleaseLike`, `_spawn_lot_release_plan` |
| `build_forward_scenario_from_csv.py` | release ARRIVAL filter (~527), wip traces |
| `load_mes_scenario.py` | `_CORE_SNAPSHOT_TABLES`, `_audit_fab_env_compat` |
| `models.py` | `MesScenario`, snapshot models pattern |

---

*End of implementation prompt.*
