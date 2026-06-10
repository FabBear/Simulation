-- Platform SSOT schema (POSTGRES_SCHEMA=simulation)
CREATE SCHEMA IF NOT EXISTS simulation;
SET search_path TO simulation;


-- FAB_BEAR V003: kpi_whatif_diff — WHAT-IF vs baseline KPI delta (simulation output)
-- Filled by tools/compare_whatif.py (or runner) after a WHATIF run completes.

CREATE TABLE IF NOT EXISTS kpi_whatif_diff (
    id                    BIGSERIAL PRIMARY KEY,
    whatif_scenario_id    VARCHAR(64) NOT NULL REFERENCES mes_scenario (scenario_id) ON DELETE CASCADE,
    baseline_scenario_id  VARCHAR(64) REFERENCES mes_scenario (scenario_id) ON DELETE SET NULL,
    baseline_run_id       VARCHAR(64) REFERENCES simulation_run (run_id) ON DELETE SET NULL,
    whatif_run_id         VARCHAR(64) NOT NULL REFERENCES simulation_run (run_id) ON DELETE CASCADE,
    level                 VARCHAR(32) NOT NULL,
    scope                 VARCHAR(256) NOT NULL,
    kpi_name              VARCHAR(128) NOT NULL,
    snapshot_time         DOUBLE PRECISION NOT NULL,
    baseline_value        DOUBLE PRECISION,
    whatif_value          DOUBLE PRECISION,
    delta                 DOUBLE PRECISION,
    computed_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_kpi_whatif_diff_whatif_run
    ON kpi_whatif_diff (whatif_run_id);

CREATE INDEX IF NOT EXISTS ix_kpi_whatif_diff_scenario_time
    ON kpi_whatif_diff (whatif_scenario_id, snapshot_time);

CREATE INDEX IF NOT EXISTS ix_kpi_whatif_diff_kpi
    ON kpi_whatif_diff (whatif_scenario_id, level, scope, kpi_name, snapshot_time);

COMMENT ON TABLE kpi_whatif_diff IS 'Per (whatif_run, baseline_run) KPI delta. Simulation output, not MES input.';

-- Optional view: latest baseline ↔ whatif KPI pair
CREATE OR REPLACE VIEW v_kpi_whatif_diff_latest AS
SELECT DISTINCT ON (whatif_scenario_id, level, scope, kpi_name)
    whatif_scenario_id, baseline_scenario_id,
    whatif_run_id, baseline_run_id,
    level, scope, kpi_name,
    snapshot_time, baseline_value, whatif_value, delta, computed_at
FROM kpi_whatif_diff
ORDER BY whatif_scenario_id, level, scope, kpi_name, computed_at DESC;

COMMENT ON VIEW v_kpi_whatif_diff_latest IS 'Latest KPI diff per (scenario, level, scope, kpi_name).';
