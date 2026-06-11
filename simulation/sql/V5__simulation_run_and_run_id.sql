-- Platform SSOT schema (POSTGRES_SCHEMA=simulation)
CREATE SCHEMA IF NOT EXISTS simulation;
SET search_path TO simulation;


-- Mirror of spring-backend Flyway V5 (apply via load_csv_to_db.py or manual psql)

CREATE TABLE IF NOT EXISTS simulation_run (
    run_id          VARCHAR PRIMARY KEY,
    source_path     VARCHAR,
    imported_at     TIMESTAMPTZ DEFAULT NOW(),
    sim_end_minutes DOUBLE PRECISION,
    note            TEXT
);

ALTER TABLE simulation_log ADD COLUMN IF NOT EXISTS run_id VARCHAR;
CREATE INDEX IF NOT EXISTS ix_simulation_log_run_id ON simulation_log (run_id);

ALTER TABLE lot_event_log ADD COLUMN IF NOT EXISTS run_id VARCHAR;
CREATE INDEX IF NOT EXISTS ix_lot_event_log_run_id ON lot_event_log (run_id);

ALTER TABLE tool_state_log ADD COLUMN IF NOT EXISTS run_id VARCHAR;
CREATE INDEX IF NOT EXISTS ix_tool_state_log_run_id ON tool_state_log (run_id);

-- KPI run_id: V6 level tables (kpi_fab/process/toolgroup/tool), not legacy kpi_snapshot.
