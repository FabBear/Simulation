# Backend handoff — KPI level tables (Flyway V6)

## PostgreSQL schema (platform SSOT)

Python simulation platform uses schema **`simulation`** (env: `POSTGRES_SCHEMA=simulation`).  
Backend/service tables may remain in **`public`**. Qualified names: `simulation.kpi_fab`, `simulation.mes_scenario`, etc.

## Summary

`kpi_snapshot` single table (with `level` column) is replaced by four physical tables:

| Table | CSV | Level |
|-------|-----|-------|
| `kpi_fab` | `kpi_fab.csv` | FAB |
| `kpi_process` | `kpi_process.csv` | PROCESS |
| `kpi_toolgroup` | `kpi_toolgroup.csv` | TOOLGROUP |
| `kpi_tool` | `kpi_tool.csv` | TOOL |

DDL: `spring-backend/src/main/resources/db/migration/V6__kpi_level_tables.sql`  
Python mirror: `simulation/sql/V6__kpi_level_tables.sql`

## Compatibility view

```sql
CREATE OR REPLACE VIEW kpi_snapshot AS
  SELECT ..., 'FAB'::varchar AS level FROM kpi_fab
  UNION ALL ...
```

- Read-only. Existing dashboards querying `kpi_snapshot` keep working.
- `KpiSnapshotEntity` maps to this VIEW (`@Immutable`).

## Writes

FabEnv and `load_csv_to_db.py` insert into level-specific tables only.

## Data migration (production backfill)

Dev/PoC: re-run simulation or `load_csv_to_db.py --truncate-run`.

If old `kpi_snapshot` table must be preserved before V6:

```sql
INSERT INTO kpi_fab (run_id, snapshot_time, scope, kpi_name, value, window_minutes, numerator, denominator, meta)
SELECT run_id, snapshot_time, scope, kpi_name, value, window_minutes, numerator, denominator, meta
FROM kpi_snapshot WHERE level = 'FAB';
-- repeat for PROCESS, TOOLGROUP, TOOL
```

Then apply V6 (drops table, creates view).

## Forward T0 from DB

`tools/build_forward_scenario_from_db.py` reads TOOL KPI from `kpi_tool` at `snapshot_time = T0`.

Trigger example:

```bash
python tools/trigger_forward_pipeline.py --source db \
  --run-id <RID> --t0 <T0> --horizon 120 \
  --scenario-id FWD_BASE_T<T0> --g-star-file <g_star.json> \
  --n-runs 30 --out-dir out/forward_T<T0>
```

No `--sim-csv-dir` required in DB mode.

## What-if DB clone (Track B)

After Forward DB-only baseline is in Postgres:

```bash
python tools/trigger_whatif_pipeline.py --source db \
  --baseline-scenario-id FWD_BASE_T<T0> \
  --whatif-scenario-id FWD_WHATIF_T<T0>_RANK1 \
  --whatif-actions actions.csv \
  --reuse-baseline-manifest out/forward_T<T0>/runs_manifest.csv \
  --t0 <T0> --horizon 120 --n-runs 30 --out-dir out/wif_T<T0>
```

Clones `mes_wip/tool/queue/release` (+ `mes_cqt` if present) from baseline scenario_id,
applies `mes_whatif_action`, validates, then Monte Carlo — no local CSV bundle.
