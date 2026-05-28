# Trigger ↔ Engine Contract

Defines how external **triggers** (ML/Agent/operator tooling) interact with the
FORWARD / WHAT-IF simulation engine in `simulation/fab_env.py`.

The engine itself is **trigger-agnostic**: it only consumes rows in Postgres and
runs them when their status is `VALIDATED`. Anything that creates those rows is
"a trigger".

---

## Roles

| Actor | Responsibility |
|---|---|
| **FORWARD trigger** (ML+rule, TBD) | Detect imminent bottleneck → emit `mes_scenario` (mode=FORWARD) + T0 snapshot + `mes_lot_release_plan`. |
| **WHAT-IF trigger** (AI Agent, TBD) | Generate intervention plans → emit `mes_scenario` (mode=WHATIF, baseline=…) + `mes_whatif_action` rows. |
| **Operator** | Manual UI/CLI alternative to either trigger. |
| **ETL (`load_mes_scenario.py`)** | CSV → Postgres. Validates and leaves status = **DRAFT**. |
| **Engine (`run_sim_forward_once.py` + `FabEnv`)** | Consumes `VALIDATED` scenarios, drives the SimPy run, writes logs and KPI diff. |

---

## Status state machine (Locked decision §8)

```
   DRAFT ─ (ETL load_mes_scenario.py) ─► DRAFT          (ETL never auto-promotes)
   DRAFT ─ (Trigger / operator review) ─► VALIDATED
   VALIDATED ─ (FabEnv.reset)          ─► RUNNING
   RUNNING ─ (FabEnv.finalize_*_run)  ─► DONE
```

Rules:

* `load_mes_scenario.py` **MUST NOT** set `status='VALIDATED'`. It always lands
  the row at `DRAFT` (or leaves any already-promoted state untouched).
* `run_sim_forward_once.py` **MUST** refuse to run anything other than
  `VALIDATED` (`exit 1` with a clear error).
* Re-running the same `scenario_id` after `DONE` is allowed; the trigger must
  set the row back to `VALIDATED` (and optionally bump `trigger_meta`). Each run
  appends a new `simulation_run` + `mes_scenario_run` row (Locked decision §7).

```sql
-- Trigger promotion example
UPDATE mes_scenario
   SET status = 'VALIDATED'
 WHERE scenario_id = 'FWD_DEMO_180'
   AND status = 'DRAFT';
```

---

## Scenario payload contract

### `mes_scenario`

| Field | Required for FORWARD | Required for WHATIF | Notes |
|---|:-:|:-:|---|
| `scenario_id` | ✅ | ✅ | Unique. |
| `mode` | `FORWARD` | `WHATIF` | Enforced by engine. |
| `t0_sim_minute` | ✅ | ✅ | Absolute fab minute that maps to SimPy 0. |
| `horizon_minutes` | ✅ | ✅ | Episode length. |
| `baseline_scenario_id` | optional | ✅ | Required for `kpi_whatif_diff`. |
| `use_master_lot_release` | optional | optional | Default false → engine ignores master `lot_release`. |
| `trigger_meta` (JSONB) | recommended | recommended | Free-form, see below. |
| `status` | `DRAFT` initially | `DRAFT` initially | Trigger promotes to `VALIDATED`. |

### `trigger_meta` (recommended schema, free-form JSON)

```json
{
  "source": "ml|agent|operator",
  "model": "xgboost_bottleneck_v3",
  "trigger_time_sim": 10792.0,
  "bottleneck_tg": "Litho_FE",
  "confidence": 0.83,
  "comment": "..."
}
```

The engine reads `trigger_meta` only for logging; the agreed schema is documented
here so dashboards can rely on it.

### `mes_whatif_action.payload_json` (Locked decision §4)

The engine is the SSOT. See [`FORWARD_WHATIF_ENGINE.md`](./FORWARD_WHATIF_ENGINE.md#what-if-action-ssot-locked-decision-4).
Unknown action kinds land in `mes_scenario_run.validation_report.unknown_actions`.

---

## Validation responsibilities

| Check | Owner |
|---|---|
| Foreign keys, type coercion, row counts | ETL (`load_mes_scenario.py`) |
| `wip.snapshot_time == t0_sim_minute` | ETL |
| Releases / actions inside `[t0, t0+horizon]` | ETL |
| `WHATIF` requires `baseline_scenario_id` and at least one `mes_whatif_action` | ETL |
| WIP route/step exists in master | ETL |
| Snapshot tool ids exist | Engine (`validation_report.missing_tools`) |
| `PROCESSING` WIP missing `processing_remaining_min` | Engine (warning; finishes immediately per Locked decision §2) |
| `VALIDATED` precondition | Trigger / operator |

ETL failures keep the row at `DRAFT`; engine warnings are non-fatal but appear
in `mes_scenario_run.validation_report` for downstream review.

---

## Output expectations

| Table | Producer | Consumer |
|---|---|---|
| `simulation_run` | FabEnv (one per run) | Anyone joining log rows. |
| `mes_scenario_run` | FabEnv | Trigger dashboards: confirm DONE + read `validation_report`. |
| `simulation_log`, `lot_event_log`, `tool_state_log` | FabEnv | KPI tools, MES dashboards. |
| `kpi_snapshot` | FabEnv | KPI dashboards. |
| `kpi_whatif_diff` | `tools/compare_whatif.py` after WHATIF run | Agent / report. |

`kpi_whatif_diff` is **simulation output**, never MES cron input (Locked
decision §6).

---

## Non-goals for triggers

* Triggers MUST NOT update `simulation_run`, `simulation_log`, KPI tables, or
  `kpi_whatif_diff` directly — those are produced by the engine.
* Triggers MUST NOT skip the `DRAFT → VALIDATED` step; that is the single
  audit hook.
* Triggers MUST NOT mutate `mes_scenario` rows in `RUNNING` state. If a fix
  is needed, wait for `DONE` (or insert a new scenario with new id).
