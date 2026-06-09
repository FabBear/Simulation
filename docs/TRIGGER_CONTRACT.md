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

### `mes_wip_snapshot.status` vocabulary (Locked)

**DB / FabEnv SSOT** — values stored in Postgres and read by `FabEnv` at T0 inject.
Do **not** use Snapshot V2 strings (`QUEUE`, `TRANSPORT`) in `mes_wip_snapshot` without
normalization.

| MES value (canonical) | Meaning |
|---|---|
| `QUEUING` | Lot waiting at a tool (queue) |
| `PROCESSING` | Lot on tool; requires `processing_remaining_min` > 0 when possible |
| `WAIT_TRANSPORT` | Lot in transit between tools |
| `HOLD` | Lot held (engine adds to `hold_lots`) |
| `WAIT_BATCH` | Lot waiting for batch formation |

| Alias (input) | Normalized to | Source |
|---|---|---|
| `QUEUE` | `QUEUING` | Snapshot V2 (`schemas/snapshot_v2.py`), Agent snapshot builder |
| `TRANSPORT` | `WAIT_TRANSPORT` | Snapshot V2 |

`load_mes_scenario.py` applies aliases on CSV/ETL load **before** insert.
Platform `build_forward_scenario_from_csv.py` already emits canonical `QUEUING` /
`PROCESSING`.

**Not the same layer:** cold-start sim CSV (`lot_events.csv`) uses `event_type`
(`ARRIVAL`, `START`, …) — not `mes_wip_snapshot.status`.

---

## Validation responsibilities

| Check | Owner |
|---|---|
| Foreign keys, type coercion, row counts | ETL (`load_mes_scenario.py`) |
| `wip.snapshot_time == t0_sim_minute` | ETL |
| Releases / actions inside `[t0, t0+horizon]` | ETL |
| `WHATIF` requires `baseline_scenario_id` and at least one `mes_whatif_action` | ETL |
| WIP route/step exists in master | ETL |
| `mes_wip_snapshot.status` canonical or alias (`QUEUE`→`QUEUING`, …) | ETL (`normalize_mes_wip_status`) |
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
| `kpi_fab`, `kpi_process`, `kpi_toolgroup`, `kpi_tool` | FabEnv | KPI dashboards (CSV 1:1). Legacy read: `kpi_snapshot` VIEW. |
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
  is needed, wait for `DONE` (or insert a new scenario with new scenario_id).

---

## Appendix — Monte Carlo replicas (Template → N× DB clone)

PoC default **N=30**. Same payload, different `scenario_id` per run (`_R01..R30`).

| Actor | Responsibility |
|---|---|
| **AI Agent** | Submit **one** template scenario (actions, T0, horizon). |
| **Platform Trigger** | `load_mes_scenario` → `clone_mes_scenarios_for_monte_carlo` → `run_monte_carlo_batch` / `run_stat_batch`. |
| **Agent (must not)** | Create `_R01..R30` manually or copy 30 CSV folders. |

**Why N replicas:** `mes_scenario.status` allows one `VALIDATED→RUNNING→DONE` cycle per
`scenario_id`. Parallel Monte Carlo requires **N distinct scenario_ids** with identical
snapshot/action rows.

**Tools:**

- `tools/clone_mes_scenarios_for_monte_carlo.py` — copy template + child rows → replicas (`DRAFT`)
- `tools/run_monte_carlo_batch.py` — clone + stat batch wrapper
- `tools/run_stat_batch.py` — promote unique IDs, parallel sim, handoff JSON (`monte_carlo` block)

**Track B (what-if):** baseline `runs_manifest.csv` is **reused** from Track A; only what-if
replicas are cloned and simulated N times.

**Track B DB mode (`--source db`):** baseline `mes_*` is **cloned from Postgres** (no local
`mes_*.csv` bundle). `make_whatif_scenario_from_db.py` → `run_monte_carlo_batch` (skips
`load_mes_scenario.py`). Requires baseline FORWARD scenario already in DB (e.g. Track A
`--source db`).

**Agent submit (example):**

```json
{
  "baseline_scenario_id": "FWD_BASE_T26820",
  "t0_sim_minute": 26820,
  "horizon_minutes": 120,
  "actions": [{ "action_kind": "LOT_HOLD", "effective_time": 26821 }],
  "monte_carlo": { "n_runs": 30 }
}
```

**Platform returns:**

```json
{
  "template_scenario_id": "FWD_WHATIF_T26820_RANK1",
  "replica_scenario_ids": ["..._R01", "..._R30"],
  "handoff_path": "out/.../agent_handoff_whatif.json"
}
```

---

## Appendix — E2E Trigger entry points (snapshot → handoff JSON)

PoC **single-command** wrappers chain snapshot/bundle → DB load → Monte Carlo → Agent handoff.
Agent logic is **not** implemented here; these tools only produce `agent_handoff_*.json`.

| Track | Tool | Output handoff |
|-------|------|----------------|
| **A — FORWARD / root cause** | `tools/trigger_forward_pipeline.py` | `agent_handoff_g_star_analysis.json` |
| **B — WHAT-IF / verification** | `tools/trigger_whatif_pipeline.py` | `agent_handoff_whatif.json` |

Shared helpers: `tools/_trigger_common.py` (`run_step`, `bundle_csv_paths`, `emit_result_json`).

### Track A example

```bash
cd FAB_BEAR/simulation
python tools/trigger_forward_pipeline.py \
  --sim-csv-dir sim_csv_out/cold_start \
  --run-id <cold_start_run_id> \
  --t0 26820 --horizon 120 \
  --scenario-id FWD_BASE_T26820 \
  --g-star-file out/ml_g_star_e2e/g_star.json \
  --baseline-csv-dir sim_csv_out \
  --n-runs 30 --parallel 8 \
  --out-dir out/forward_trigger_T26820
```

Steps (subprocess chain): `build_forward_scenario_from_csv.py` → `load_mes_scenario.py` → `run_monte_carlo_batch.py --track g_star_analysis`.

Success stdout (final line block):

```json
{
  "track": "g_star_analysis",
  "template_scenario_id": "FWD_BASE_T26820",
  "replica_scenario_ids": ["FWD_BASE_T26820_R01", "..."],
  "handoff_path": "out/forward_trigger_T26820/agent_handoff_g_star_analysis.json",
  "runs_manifest": "out/forward_trigger_T26820/runs_manifest.csv"
}
```

Flags: `--dry-run` (print commands only), `--skip-snapshot`, `--skip-load` (reuse prior bundle/DB row).

### Track B example (CSV baseline bundle)

```bash
python tools/trigger_whatif_pipeline.py \
  --source csv \
  --baseline-scenario-id FWD_BASE_T26820 \
  --baseline-bundle-dir scenario_out/FWD_BASE_T26820 \
  --reuse-baseline-manifest out/forward_trigger_T26820/runs_manifest.csv \
  --whatif-scenario-id FWD_WHATIF_T26820_RANK1 \
  --whatif-actions agent_actions/rank1_actions.csv \
  --t0 26820 --horizon 120 \
  --focus-scopes "Diffusion_FE_120#1" \
  --n-runs 30 --parallel 8 \
  --out-dir out/whatif_trigger_rank1
```

Steps: `make_whatif_scenario_bundle.py` → `load_mes_scenario.py` → `run_monte_carlo_batch.py --track whatif` (baseline manifest **reused**, baseline sim not re-run).

### Track B example (DB baseline clone — CSV-free)

```bash
python tools/trigger_whatif_pipeline.py \
  --source db \
  --baseline-scenario-id FWD_BASE_T26820 \
  --reuse-baseline-manifest out/forward_T26820/runs_manifest.csv \
  --whatif-scenario-id FWD_WHATIF_T26820_RANK1 \
  --whatif-actions agent_actions/rank1_actions.csv \
  --t0 26820 --horizon 120 \
  --n-runs 30 --parallel 8 \
  --out-dir out/whatif_T26820
```

Steps: `make_whatif_scenario_from_db.py` → `run_monte_carlo_batch.py --track whatif`. No `--baseline-bundle-dir`, no local `mes_*.csv`.

Success stdout:

```json
{
  "track": "whatif",
  "template_scenario_id": "FWD_WHATIF_T26820_RANK1",
  "baseline_scenario_id": "FWD_BASE_T26820",
  "replica_scenario_ids": ["..."],
  "handoff_path": "out/whatif_trigger_rank1/agent_handoff_whatif.json",
  "paired_manifest": "out/whatif_trigger_rank1/paired_manifest.csv"
}
```

Fail-fast: missing baseline manifest or fewer than `n_runs` ok rows → exit 1 before handoff.
