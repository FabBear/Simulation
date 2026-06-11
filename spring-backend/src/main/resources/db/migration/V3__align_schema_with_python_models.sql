-- V3__align_schema_with_python_models.sql
-- Goal: Align Spring Flyway schema with Python SQLAlchemy models.py (single source of truth).
-- Strategy: append-only, idempotent. Safe for:
--   (a) Fresh DB (V1 -> V2 -> V3)
--   (b) DB previously initialized only by V1
--   (c) DB previously initialized by Python init_db.py (full Python ORM schema already present)
--   (d) DB that manually applied SMT_2000_Simulation/sql/V2__tool_state_log_aggregate_columns.sql
-- Does NOT touch V1/V2 migrations (Flyway checksum stability).

-- =========================================================
-- 1. Column additions on existing tables (V1 baseline)
-- =========================================================

-- 1-1. toolgroup: add tool_wakeup_ranking (used by ToolGroup model)
ALTER TABLE toolgroup
    ADD COLUMN IF NOT EXISTS tool_wakeup_ranking VARCHAR;

-- 1-2. pm_event: add distribution / first-occurrence metadata columns
ALTER TABLE pm_event
    ADD COLUMN IF NOT EXISTS duration_dist VARCHAR;
ALTER TABLE pm_event
    ADD COLUMN IF NOT EXISTS foa_dist VARCHAR;
ALTER TABLE pm_event
    ADD COLUMN IF NOT EXISTS foa_unit VARCHAR;

-- 1-3. simulation_log: add physical tool_id (FabEnv writes per-unit tool id)
ALTER TABLE simulation_log
    ADD COLUMN IF NOT EXISTS tool_id VARCHAR;
CREATE INDEX IF NOT EXISTS ix_simulation_log_tool_id
    ON simulation_log (tool_id);

-- =========================================================
-- 2. New log tables required by FabEnv but missing in V1
--    (mirrors Python models.py exactly: column names, nullable, defaults)
-- =========================================================

-- 2-1. lot_event_log  (FabEnv._log_lot_event)
CREATE TABLE IF NOT EXISTS lot_event_log (
    id          SERIAL PRIMARY KEY,
    lot_id      VARCHAR,
    product     VARCHAR,
    route_id    VARCHAR,
    step_seq    INTEGER,
    tool_group  VARCHAR,
    tool_id     VARCHAR,
    event_type  VARCHAR,
    event_time  DOUBLE PRECISION,
    detail_1    VARCHAR,
    detail_2    VARCHAR
);
CREATE INDEX IF NOT EXISTS ix_lot_event_log_lot_id     ON lot_event_log (lot_id);
CREATE INDEX IF NOT EXISTS ix_lot_event_log_tool_id    ON lot_event_log (tool_id);
CREATE INDEX IF NOT EXISTS ix_lot_event_log_event_type ON lot_event_log (event_type);
CREATE INDEX IF NOT EXISTS ix_lot_event_log_event_time ON lot_event_log (event_time);

-- 2-2. tool_state_log  (FabEnv._log_tool_state, ToolGroup-level aggregate)
--      Aggregate unit-count columns are included up-front so fresh DBs get them via CREATE.
--      The ALTERs below cover DBs that already had the V1-era table (or ran the standalone
--      SMT_2000_Simulation/sql/V2__tool_state_log_aggregate_columns.sql).
CREATE TABLE IF NOT EXISTS tool_state_log (
    id                 SERIAL PRIMARY KEY,
    tool_group         VARCHAR,
    tool_id            VARCHAR,
    state              VARCHAR,
    state_change_time  DOUBLE PRECISION,
    setup_name         VARCHAR,
    lot_id             VARCHAR,
    reason             VARCHAR,
    idle_units         INTEGER,
    run_units          INTEGER,
    setup_units        INTEGER,
    down_pm_units      INTEGER,
    down_bm_units      INTEGER
);
ALTER TABLE tool_state_log ADD COLUMN IF NOT EXISTS idle_units    INTEGER;
ALTER TABLE tool_state_log ADD COLUMN IF NOT EXISTS run_units     INTEGER;
ALTER TABLE tool_state_log ADD COLUMN IF NOT EXISTS setup_units   INTEGER;
ALTER TABLE tool_state_log ADD COLUMN IF NOT EXISTS down_pm_units INTEGER;
ALTER TABLE tool_state_log ADD COLUMN IF NOT EXISTS down_bm_units INTEGER;

CREATE INDEX IF NOT EXISTS ix_tool_state_log_tool_group        ON tool_state_log (tool_group);
CREATE INDEX IF NOT EXISTS ix_tool_state_log_tool_id           ON tool_state_log (tool_id);
CREATE INDEX IF NOT EXISTS ix_tool_state_log_state             ON tool_state_log (state);
CREATE INDEX IF NOT EXISTS ix_tool_state_log_state_change_time ON tool_state_log (state_change_time);

-- 2-3. active_cqt_timer  (FabEnv._sync_cqt_table)
CREATE TABLE IF NOT EXISTS active_cqt_timer (
    id             SERIAL PRIMARY KEY,
    lot_id         VARCHAR,
    start_step     INTEGER,
    target_step    INTEGER,
    deadline_time  DOUBLE PRECISION,
    started_at     DOUBLE PRECISION,
    is_active      BOOLEAN DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS ix_active_cqt_timer_lot_id        ON active_cqt_timer (lot_id);
CREATE INDEX IF NOT EXISTS ix_active_cqt_timer_deadline_time ON active_cqt_timer (deadline_time);

-- 2-4. realtime_wip_summary  (FabEnv._record_wip_snapshot, every 1 sim minute)
CREATE TABLE IF NOT EXISTS realtime_wip_summary (
    id               SERIAL PRIMARY KEY,
    snapshot_time    DOUBLE PRECISION,
    tool_group       VARCHAR,
    tool_id          VARCHAR,
    waiting_lots     INTEGER DEFAULT 0,
    processing_lots  INTEGER DEFAULT 0,
    avg_queue_time   DOUBLE PRECISION DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS ix_realtime_wip_summary_snapshot_time ON realtime_wip_summary (snapshot_time);
CREATE INDEX IF NOT EXISTS ix_realtime_wip_summary_tool_group    ON realtime_wip_summary (tool_group);
CREATE INDEX IF NOT EXISTS ix_realtime_wip_summary_tool_id       ON realtime_wip_summary (tool_id);

-- =========================================================
-- 3. Post-conditions (intentional no-ops for documentation)
-- =========================================================
-- After this migration, the following Python ORM tables/columns are guaranteed to exist:
--   toolgroup.tool_wakeup_ranking
--   pm_event.duration_dist, pm_event.foa_dist, pm_event.foa_unit
--   simulation_log.tool_id (+ index)
--   lot_event_log, tool_state_log (with aggregate columns), active_cqt_timer, realtime_wip_summary
-- FabEnv DB writes (which were silently swallowed by try/except) should now succeed.
