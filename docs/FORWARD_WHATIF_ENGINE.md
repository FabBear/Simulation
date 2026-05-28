# FORWARD / WHAT-IF Simulation Engine

This document describes how the FabEnv simulation engine in
`simulation/fab_env.py` runs **FORWARD** and **WHAT-IF** scenarios on top of the
existing rule/PPO dispatcher.

For schema and ETL details see
[`MES_FORWARD_WHATIF_SCHEMA.md`](./MES_FORWARD_WHATIF_SCHEMA.md). For the
contract between the engine and external triggers (ML/Agent) see
[`TRIGGER_CONTRACT.md`](./TRIGGER_CONTRACT.md).

---

## Mental model

```
            ┌──────────────────────────┐
   T0 ──►   │  T0 snapshot tables      │   ──► FabEnv.reset(options=...)
            │  • mes_wip_snapshot      │
            │  • mes_tool_snapshot     │
            │  • mes_tool_queue_snap   │
            │  • mes_cqt_snapshot      │
            └──────────────────────────┘
                       │
                       ▼
            ┌──────────────────────────┐
            │  Releases / Actions      │
            │  • mes_lot_release_plan  │   FORWARD + WHATIF
            │  • mes_whatif_action     │   WHATIF only
            └──────────────────────────┘
                       │
                       ▼
            ┌──────────────────────────┐
            │  FabEnv (SimPy 0..H)     │
            │  rule / PPO dispatch     │
            └──────────────────────────┘
                       │
                       ▼
            ┌──────────────────────────┐
            │  Logs (absolute t = T0+now)
            │  • simulation_log        │
            │  • lot_event_log         │
            │  • tool_state_log        │
            │  • kpi_snapshot          │
            │  + mes_scenario_run      │
            │  + kpi_whatif_diff (WHATIF)
            └──────────────────────────┘
```

Cold start (no `scenario_id`) keeps the legacy behaviour: master `lot_release`
spawns from `start_date`, SimPy clock is absolute (offset 0).

---

## Time handling — sim clock offset (Locked decision §1)

| Concept | Frame | Notes |
|---|---|---|
| `sim_env.now` | relative (`0..horizon`) | SimPy clock; resets to 0 every reset |
| `_sim_clock_offset` | absolute fab minute | `= scenario.t0_sim_minute` |
| `_sim_now_abs()` | absolute | `= sim_env.now + offset` (used for every log/KPI time field) |
| DB inputs (`due_date_sim`, `release_time`, `effective_time`, CQT `deadline_time`) | absolute | converted to relative on ingest via `_abs_to_rel()` |

Helpers:

```text
_sim_now_abs()         -> float   absolute fab minute
_abs_to_rel(t_abs)     -> float   max(0, t_abs - offset)
_rel_to_abs(t_rel)     -> float   t_rel + offset
_timeout_until_abs(t)             SimPy timeout until absolute minute t
```

Cold start sets `offset = 0` so `_sim_now_abs() == sim_env.now` and all behaviour
is identical.

---

## `FabEnv.reset(options=…)`

```python
env = FabEnv()
env.reset(options={"scenario_id": "FWD_DEMO_180"})
```

| Step | Action |
|---|---|
| 1 | Read `MesScenario` row by `scenario_id`. |
| 2 | Set `_sim_clock_offset = t0`, `sim_end_minutes = horizon`. |
| 3 | `_skip_master_lot_release = not use_master_lot_release` (FORWARD/WHATIF default = True). |
| 4 | `_build_simulation()` — load master tables exactly like cold start, but skip master `_source_process` spawning when `_skip_master_lot_release`. |
| 5 | `_apply_scenario_overrides()` — see below. |
| 6 | `simulation_run` + `mes_scenario_run` rows are inserted. |
| 7 | `MesScenario.status` transitions `VALIDATED -> RUNNING`. |

`SIM_SCENARIO_ID` env var is read as a fallback to `options["scenario_id"]`.

---

## `_apply_scenario_overrides`

Ordered list of actions performed inside SimPy, all in **relative** time after
the ingest converted absolute DB times via `_abs_to_rel`:

1. `_inject_t0_tools` — restore `current_setup`, `op_state`. `DOWN_PM` / `DOWN_BM` units
   spawn a holding process (`_inject_down_hold`) so dispatch waits until the
   master-driven duration ends. (Locked decision §3)
2. `_inject_t0_wip` — for each WIP lot:
   * Register in `active_lots_data` / `issued_lot_names` / `_kpi_lot_rtf`.
   * `status == PROCESSING` → resume `_resume_processing_wip` (uses
     `processing_remaining_min`). If that field is NULL or 0 the tool is treated
     as **empty** and the lot **finishes immediately** (Locked decision §2),
     emitting a `validation_report.warnings` entry.
   * `status` in {`QUEUING`, `WAIT_TRANSPORT`, `WAIT_BATCH`} → spawn
     `_lot_process_from(start_idx=...)` which is `_lot_process(..., start_idx=i, suppress_init_logs=True)`.
     No `ARRIVAL` log is emitted for T0 lots (validation requirement).
   * `status == HOLD` → in addition to the spawn, the lot id is added to
     `hold_lots` so dispatch skips it.
3. `_inject_t0_queues` — seed each tool’s SimPy queue with `permission_event`
   payloads matching the T0 ordering.
4. `_inject_t0_cqt` — restore `active_cqt[lot_id]` from `mes_cqt_snapshot`.
5. (WHATIF only) `_load_whatif_actions` — apply immediate actions, schedule
   deferred ones via `_whatif_action_loop`.
6. `_spawn_lot_release_plan` — for each `mes_lot_release_plan` row, build a
   `_LotReleaseLike` adapter and spawn `_source_process(adapter)`. The adapter
   carries `plan_id` so `SKIP_RELEASE` overrides can prevent spawning later.

---

## WHAT-IF action SSOT (Locked decision §4)

`mes_whatif_action.payload_json` schema — **the engine is the source of truth**.
Agents and ETL must produce the same keys.

| `action_kind` | `payload_json` | Engine behaviour |
|---|---|---|
| `LOT_PRIORITY` | `{"priority": int}` | Update `active_lots_data[lot].priority` and any in-queue payload. |
| `LOT_HOLD` | `{}` or `{"reason": str}` | Add lot to `hold_lots`; dispatch skips it. |
| `LOT_RELEASE` | `{}` | Remove from `hold_lots`. |
| `DISPATCH_RULE_OVERRIDE` | `{"tool_group": str, "dispatch_rule": str}` | Override `_parse_dispatch_flags` for that TG. |
| `FORCE_TOOL` | `{"tool_id": str, "once": bool, "tool_group": str?}` | `_choose_tool_for_lot` returns that tool; `_select_dispatch_candidate` jumps the queue. `once=True` pops the override after one use. (Locked decision §5) |
| `SKIP_RELEASE` | `{"mes_lot_release_plan_id": int}` | `_source_process` skips spawning lots from that plan id. |
| `ADD_RELEASE` | `{"product_name", "route_name", "release_time", ...}` | Immediately spawn a new `_LotReleaseLike` release. |

JSON key names **must not change**. Unknown keys are tolerated; unknown
`action_kind` is logged to `mes_scenario_run.validation_report`.

---

## Dispatch hooks summary

| Source | Where |
|---|---|
| `dispatch_rule_override` (DISPATCH_RULE_OVERRIDE) | `_parse_dispatch_flags(toolgroup)` — overrides string before tokenising. |
| `hold_lots` (LOT_HOLD / WIP HOLD) | `_select_dispatch_candidate`, `_dispatch_queue_index` — held lots cannot be chosen. |
| `force_next_tool` (FORCE_TOOL) | `_choose_tool_for_lot` (tool unit pin) **and** `_select_dispatch_candidate` (queue jump on that unit). `once=True` removes after one use. |
| `skip_release_ids` (SKIP_RELEASE) | `_source_process._release_one_lot` — early return when `plan_id` is in the set. |

---

## Output

All log writes go through helpers that add `_sim_clock_offset` so external
consumers always see absolute fab time:

| Function | Time field |
|---|---|
| `_log_lot_event` | `ev_time = _sim_now_abs()` |
| `_log_process` | `arrive_time/start_time/end_time += offset` |
| `_log_tool_state` | `t = _sim_now_abs()` |
| `_record_wip_snapshot` | `snapshot_time = _sim_now_abs()` |
| `_log_kpi_snapshot` | `snapshot_time = rel + offset` |
| `_sync_cqt_table` | `deadline_time/started_at += offset` |

In cold start `offset == 0` so all of the above are bit-equivalent to the
previous behaviour.

---

## Run summary tables

| Table | Notes |
|---|---|
| `simulation_run` | One row per FabEnv episode (`source_path = scenario:<id>` when scenario mode). |
| `mes_scenario_run` | One row per scenario execution; `started_at`, `finished_at`, `validation_report` (JSON: `missing_tools`, `missing_routes`, `missing_steps`, `warnings`, `action_errors`, `unknown_actions`). |
| `simulation_log`, `lot_event_log`, `tool_state_log`, `kpi_snapshot` | Same schemas as cold-start; times are absolute (`T0 + sim_env.now`). |
| `kpi_whatif_diff` | WHAT-IF only — filled by `tools/compare_whatif.py` after the run. |

`mes_scenario.status` transitions on the engine side:

```
   VALIDATED ── reset() ──► RUNNING ── finalize_mes_scenario_run() ──► DONE
```

Re-running the same scenario keeps cumulative `simulation_run` / `mes_scenario_run`
rows (Locked decision §7).

---

## CLI usage

### FORWARD

```bash
# 1. Load CSVs into Postgres (status=DRAFT)
.venv/bin/python load_mes_scenario.py \
    --scenario-id FWD_DEMO_180 --mode FORWARD --t0 10800 --horizon 180 \
    --wip sample_csv/mes_wip_snapshot.csv \
    --tools sample_csv/mes_tool_snapshot.csv \
    --queues sample_csv/mes_tool_queue_snapshot.csv \
    --releases sample_csv/mes_lot_release_plan.csv

# 2. Trigger / operator promotes to VALIDATED
psql ... -c "UPDATE mes_scenario SET status='VALIDATED' WHERE scenario_id='FWD_DEMO_180'"

# 3. Run
.venv/bin/python run_sim_forward_once.py --scenario-id FWD_DEMO_180
```

### WHAT-IF

```bash
.venv/bin/python load_mes_scenario.py \
    --scenario-id WHATIF_DEMO_180 --mode WHATIF --t0 10800 --horizon 180 \
    --baseline FWD_DEMO_180 \
    --wip ... --tools ... --queues ... --releases ... \
    --whatif sample_csv/mes_whatif_action.csv

# Trigger promotes to VALIDATED, then:
.venv/bin/python run_sim_forward_once.py --scenario-id WHATIF_DEMO_180

# Diff KPIs vs baseline
.venv/bin/python tools/compare_whatif.py --whatif-scenario WHATIF_DEMO_180
```

---

## Environment variables

| Var | Default | Meaning |
|---|---|---|
| `SIM_SCENARIO_ID` | — | Fallback to `reset(options=…)["scenario_id"]`. |
| `SIM_CSV_DIR` | `./sim_csv_out` | Where CSV mirrors of logs are written. |
| `SIM_END_MINUTES` | `200000` | Cold-start episode length; **scenario horizon overrides this**. |
| `DISPATCH_MODE` | `rule` | `rl` to enable PPO. |
| `KPI_INSTANT_PERIOD_MIN` | `60` | KPI snapshot cadence (instant). |
| `KPI_UTIL_WINDOW_MIN` | `60` | KPI utilization window. |
| `KPI_TAT_WINDOW_MIN` | `60` | TAT window. |
| `KPI_THROUGHPUT_WINDOW_MIN` | `1440` | Throughput window. |

---

## Non-goals (intentional)

* Full MES TRACK_IN / TRACK_OUT replay (`DISPATCH_MODE=mes_replay` removed).
* `predecessor_event_id`.
* Deterministic future PM/BD calendar (master tables remain stochastic).
* ML/Agent trigger code — out of scope for this engine task. The contract lives
  in [`TRIGGER_CONTRACT.md`](./TRIGGER_CONTRACT.md).
