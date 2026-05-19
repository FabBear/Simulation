-- V4__kpi_snapshot.sql
-- Goal: Introduce a long-format KPI snapshot table consumed by FabEnv._kpi_snapshot_loop.
-- Strategy: append-only, idempotent. Mirrors `KpiSnapshot` in Python `models.py`.
--   - No changes to V1/V2/V3 (Flyway checksum stability).
--   - Does NOT modify any raw event table; KPIs live in their own table to avoid time-axis
--     and grain conflicts with `lot_event_log` / `tool_state_log` / `simulation_log`.

CREATE TABLE IF NOT EXISTS kpi_snapshot (
    id              SERIAL PRIMARY KEY,
    snapshot_time   DOUBLE PRECISION,         -- simulation minute when the snapshot was taken
    level           VARCHAR,                  -- FAB | PROCESS | TOOLGROUP | TOOL
    scope           VARCHAR,                  -- "*" (FAB) | process | toolgroup | tool_id
    kpi_name        VARCHAR,                  -- rtf, throughput_24h, tat_min, q_time_min, wip,
                                              -- utilization, available_tool_ratio, setup_ratio,
                                              -- down_ratio, wait_ratio, oee_estimate ...
    value           DOUBLE PRECISION,         -- weighted sum or ratio (NEVER an avg-of-avgs)
    window_minutes  INTEGER,                  -- 60, 1440 ... NULL means instantaneous
    numerator       DOUBLE PRECISION,         -- raw sum captured for post-hoc recomputation
    denominator     DOUBLE PRECISION,         -- raw denominator captured for post-hoc recomputation
    meta            TEXT                      -- optional JSON payload (extra dimensions)
);

CREATE INDEX IF NOT EXISTS ix_kpi_snapshot_snapshot_time
    ON kpi_snapshot (snapshot_time);
CREATE INDEX IF NOT EXISTS ix_kpi_snapshot_level
    ON kpi_snapshot (level);
CREATE INDEX IF NOT EXISTS ix_kpi_snapshot_scope
    ON kpi_snapshot (scope);
CREATE INDEX IF NOT EXISTS ix_kpi_snapshot_kpi_name
    ON kpi_snapshot (kpi_name);

-- Composite index for the most common query: "give me KPI X for scope Y over time".
CREATE INDEX IF NOT EXISTS ix_kpi_snapshot_lookup
    ON kpi_snapshot (level, scope, kpi_name, snapshot_time);
