-- V6__kpi_level_tables.sql
-- Split kpi_snapshot (level column) into four level-specific tables matching CSV outputs.
-- Provides read-only kpi_snapshot VIEW for legacy queries.

DROP VIEW IF EXISTS kpi_snapshot;

DROP TABLE IF EXISTS kpi_snapshot CASCADE;

CREATE TABLE IF NOT EXISTS kpi_fab (
    id              SERIAL PRIMARY KEY,
    run_id          VARCHAR,
    snapshot_time   DOUBLE PRECISION,
    scope           VARCHAR,
    kpi_name        VARCHAR,
    value           DOUBLE PRECISION,
    window_minutes  INTEGER,
    numerator       DOUBLE PRECISION,
    denominator     DOUBLE PRECISION,
    meta            TEXT
);

CREATE TABLE IF NOT EXISTS kpi_process (
    id              SERIAL PRIMARY KEY,
    run_id          VARCHAR,
    snapshot_time   DOUBLE PRECISION,
    scope           VARCHAR,
    kpi_name        VARCHAR,
    value           DOUBLE PRECISION,
    window_minutes  INTEGER,
    numerator       DOUBLE PRECISION,
    denominator     DOUBLE PRECISION,
    meta            TEXT
);

CREATE TABLE IF NOT EXISTS kpi_toolgroup (
    id              SERIAL PRIMARY KEY,
    run_id          VARCHAR,
    snapshot_time   DOUBLE PRECISION,
    scope           VARCHAR,
    kpi_name        VARCHAR,
    value           DOUBLE PRECISION,
    window_minutes  INTEGER,
    numerator       DOUBLE PRECISION,
    denominator     DOUBLE PRECISION,
    meta            TEXT
);

CREATE TABLE IF NOT EXISTS kpi_tool (
    id              SERIAL PRIMARY KEY,
    run_id          VARCHAR,
    snapshot_time   DOUBLE PRECISION,
    scope           VARCHAR,
    kpi_name        VARCHAR,
    value           DOUBLE PRECISION,
    window_minutes  INTEGER,
    numerator       DOUBLE PRECISION,
    denominator     DOUBLE PRECISION,
    meta            TEXT
);

CREATE INDEX IF NOT EXISTS ix_kpi_fab_run_id ON kpi_fab (run_id);
CREATE INDEX IF NOT EXISTS ix_kpi_fab_snapshot_time ON kpi_fab (snapshot_time);
CREATE INDEX IF NOT EXISTS ix_kpi_fab_lookup ON kpi_fab (run_id, scope, kpi_name, snapshot_time);

CREATE INDEX IF NOT EXISTS ix_kpi_process_run_id ON kpi_process (run_id);
CREATE INDEX IF NOT EXISTS ix_kpi_process_snapshot_time ON kpi_process (snapshot_time);
CREATE INDEX IF NOT EXISTS ix_kpi_process_lookup ON kpi_process (run_id, scope, kpi_name, snapshot_time);

CREATE INDEX IF NOT EXISTS ix_kpi_toolgroup_run_id ON kpi_toolgroup (run_id);
CREATE INDEX IF NOT EXISTS ix_kpi_toolgroup_snapshot_time ON kpi_toolgroup (snapshot_time);
CREATE INDEX IF NOT EXISTS ix_kpi_toolgroup_lookup ON kpi_toolgroup (run_id, scope, kpi_name, snapshot_time);

CREATE INDEX IF NOT EXISTS ix_kpi_tool_run_id ON kpi_tool (run_id);
CREATE INDEX IF NOT EXISTS ix_kpi_tool_snapshot_time ON kpi_tool (snapshot_time);
CREATE INDEX IF NOT EXISTS ix_kpi_tool_lookup ON kpi_tool (run_id, scope, kpi_name, snapshot_time);

CREATE OR REPLACE VIEW kpi_snapshot AS
SELECT id, run_id, snapshot_time, 'FAB'::varchar AS level, scope, kpi_name, value,
       window_minutes, numerator, denominator, meta
FROM kpi_fab
UNION ALL
SELECT id, run_id, snapshot_time, 'PROCESS', scope, kpi_name, value,
       window_minutes, numerator, denominator, meta
FROM kpi_process
UNION ALL
SELECT id, run_id, snapshot_time, 'TOOLGROUP', scope, kpi_name, value,
       window_minutes, numerator, denominator, meta
FROM kpi_toolgroup
UNION ALL
SELECT id, run_id, snapshot_time, 'TOOL', scope, kpi_name, value,
       window_minutes, numerator, denominator, meta
FROM kpi_tool;
