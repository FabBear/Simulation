-- Platform SSOT schema (POSTGRES_SCHEMA=simulation)
CREATE SCHEMA IF NOT EXISTS simulation;
SET search_path TO simulation;


-- Tool group–level aggregate columns for tool_state_log (FabEnv aggregate logging).
--
-- NOTE (2026-05): This standalone patch is now superseded by the Spring Flyway
-- migration `spring-backend/src/main/resources/db/migration/V3__align_schema_with_python_models.sql`,
-- which both CREATEs `tool_state_log` (with these aggregate columns) and re-applies
-- the same ALTER ... IF NOT EXISTS statements for legacy DBs.
--
-- Keep this file only as a manual escape hatch for environments where Flyway is
-- not used at all (pure Python `init_db.py`). In any Spring-managed DB you do NOT
-- need to run this file by hand — `docker compose up` will apply V3 automatically.

ALTER TABLE tool_state_log ADD COLUMN IF NOT EXISTS idle_units INTEGER;
ALTER TABLE tool_state_log ADD COLUMN IF NOT EXISTS run_units INTEGER;
ALTER TABLE tool_state_log ADD COLUMN IF NOT EXISTS setup_units INTEGER;
ALTER TABLE tool_state_log ADD COLUMN IF NOT EXISTS down_pm_units INTEGER;
ALTER TABLE tool_state_log ADD COLUMN IF NOT EXISTS down_bm_units INTEGER;
