-- Platform SSOT schema (POSTGRES_SCHEMA=simulation)
CREATE SCHEMA IF NOT EXISTS simulation;
SET search_path TO simulation;


-- FAB_BEAR MES schema V2: FORWARD / WHAT-IF (REPLAY deprecated)
-- Requires V001 applied. Migrates replay schedule grid → forward sparse inputs.

-- ---------------------------------------------------------------------------
-- 1) mes_scenario: mode + metadata
-- ---------------------------------------------------------------------------
ALTER TABLE mes_scenario
    ADD COLUMN IF NOT EXISTS baseline_scenario_id VARCHAR(64)
        REFERENCES mes_scenario (scenario_id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS trigger_meta JSONB,
    ADD COLUMN IF NOT EXISTS use_master_lot_release BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE mes_scenario
SET mode = 'FORWARD'
WHERE mode IN ('REPLAY', 'REPLAY_WHATIF');

ALTER TABLE mes_scenario DROP CONSTRAINT IF EXISTS ck_mes_scenario_mode;
ALTER TABLE mes_scenario
    ADD CONSTRAINT ck_mes_scenario_mode
        CHECK (mode IN ('FORWARD', 'WHATIF'));

ALTER TABLE mes_scenario ALTER COLUMN mode SET DEFAULT 'FORWARD';

COMMENT ON COLUMN mes_scenario.baseline_scenario_id IS 'WHAT-IF: reference FORWARD scenario for diff';
COMMENT ON COLUMN mes_scenario.trigger_meta IS 'JSON: bottleneck TG, ML trigger, snapshot_time, etc.';
COMMENT ON COLUMN mes_scenario.use_master_lot_release IS 'If true, FabEnv filters lot_release [t0,t0+x] instead of mes_lot_release_plan';

-- ---------------------------------------------------------------------------
-- 2) Deprecate REPLAY schedule grid
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS v_schedule_adherence;

DROP INDEX IF EXISTS uq_mes_schedule_track_in;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'mes_schedule_event') THEN
        CREATE TABLE IF NOT EXISTS _archive_mes_schedule_replay AS
        SELECT * FROM mes_schedule_event WHERE FALSE;

        INSERT INTO _archive_mes_schedule_replay
        SELECT * FROM mes_schedule_event
        WHERE event_kind IN ('TRACK_IN', 'TRACK_OUT', 'TRANSPORT_START', 'ARRIVE_QUEUE');

        DELETE FROM mes_schedule_event
        WHERE event_kind IN ('TRACK_IN', 'TRACK_OUT', 'TRANSPORT_START', 'ARRIVE_QUEUE');

        DROP TABLE mes_schedule_event;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 3) mes_forward_input_event (sparse: HOLD / RELEASE / FAB_ARRIVAL)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mes_forward_input_event (
    id                BIGSERIAL PRIMARY KEY,
    scenario_id       VARCHAR(64) NOT NULL REFERENCES mes_scenario (scenario_id) ON DELETE CASCADE,
    seq               INTEGER NOT NULL DEFAULT 0,
    lot_id            VARCHAR(128) NOT NULL,
    route_id          VARCHAR(128) NOT NULL,
    step_seq          INTEGER,
    event_kind        VARCHAR(32) NOT NULL,
    scheduled_time    DOUBLE PRECISION NOT NULL,
    tool_group        VARCHAR(128),
    tool_id           VARCHAR(128),
    priority          INTEGER,
    due_date_sim      DOUBLE PRECISION,
    mes_row_hash      VARCHAR(64),
    source_line_no    INTEGER,
    note              TEXT,
    CONSTRAINT ck_mes_forward_input_event_kind
        CHECK (event_kind IN ('FAB_ARRIVAL', 'HOLD', 'RELEASE')),
    CONSTRAINT ck_mes_forward_input_tool_id_format
        CHECK (tool_id IS NULL OR tool_id ~ '^[^#]+#[1-9][0-9]*$')
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_mes_forward_input_row_hash
    ON mes_forward_input_event (scenario_id, mes_row_hash)
    WHERE mes_row_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_mes_forward_input_scenario_time
    ON mes_forward_input_event (scenario_id, scheduled_time);

CREATE INDEX IF NOT EXISTS ix_mes_forward_input_scenario_lot
    ON mes_forward_input_event (scenario_id, lot_id);

-- ---------------------------------------------------------------------------
-- 4) mes_lot_release_plan (T0..T0+x new fab releases — FORWARD)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mes_lot_release_plan (
    id                    BIGSERIAL PRIMARY KEY,
    scenario_id           VARCHAR(64) NOT NULL REFERENCES mes_scenario (scenario_id) ON DELETE CASCADE,
    source_lot_release_id INTEGER,
    product_name          VARCHAR(128) NOT NULL,
    route_name            VARCHAR(128) NOT NULL,
    release_time          DOUBLE PRECISION NOT NULL,
    lots_count            INTEGER NOT NULL DEFAULT 1,
    release_interval      DOUBLE PRECISION,
    lot_name_prefix       VARCHAR(128),
    lot_type              VARCHAR(128),
    priority              INTEGER,
    due_date_sim          DOUBLE PRECISION,
    wafers_per_lot        INTEGER,
    is_super_hot          BOOLEAN NOT NULL DEFAULT FALSE,
    mes_row_hash          VARCHAR(64),
    source_line_no        INTEGER,
    CONSTRAINT ck_mes_lot_release_lots_count CHECK (lots_count >= 1)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_mes_lot_release_row_hash
    ON mes_lot_release_plan (scenario_id, mes_row_hash)
    WHERE mes_row_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_mes_lot_release_scenario_time
    ON mes_lot_release_plan (scenario_id, release_time);

-- ---------------------------------------------------------------------------
-- 5) mes_whatif_action (WHAT-IF deltas only)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mes_whatif_action (
    id                  BIGSERIAL PRIMARY KEY,
    scenario_id         VARCHAR(64) NOT NULL REFERENCES mes_scenario (scenario_id) ON DELETE CASCADE,
    seq                 INTEGER NOT NULL DEFAULT 0,
    action_kind         VARCHAR(64) NOT NULL,
    effective_time      DOUBLE PRECISION NOT NULL,
    lot_id              VARCHAR(128),
    route_id            VARCHAR(128),
    step_seq            INTEGER,
    tool_group          VARCHAR(128),
    tool_id             VARCHAR(128),
    payload_json        JSONB,
    source              VARCHAR(32) NOT NULL DEFAULT 'AGENT',
    mes_row_hash        VARCHAR(64),
    CONSTRAINT ck_mes_whatif_action_kind
        CHECK (action_kind IN (
            'LOT_PRIORITY', 'LOT_HOLD', 'LOT_RELEASE',
            'DISPATCH_RULE_OVERRIDE', 'FORCE_TOOL',
            'SKIP_RELEASE', 'ADD_RELEASE'
        )),
    CONSTRAINT ck_mes_whatif_tool_id_format
        CHECK (tool_id IS NULL OR tool_id ~ '^[^#]+#[1-9][0-9]*$')
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_mes_whatif_action_row_hash
    ON mes_whatif_action (scenario_id, mes_row_hash)
    WHERE mes_row_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_mes_whatif_scenario_time
    ON mes_whatif_action (scenario_id, effective_time);

-- ---------------------------------------------------------------------------
-- 6) mes_operating_event (optional P2: HOLD/SCRAP/REWORK from MES calendar)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mes_operating_event (
    id              BIGSERIAL PRIMARY KEY,
    scenario_id     VARCHAR(64) NOT NULL REFERENCES mes_scenario (scenario_id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL DEFAULT 0,
    lot_id          VARCHAR(128) NOT NULL,
    route_id        VARCHAR(128),
    step_seq        INTEGER,
    event_kind      VARCHAR(32) NOT NULL,
    scheduled_time  DOUBLE PRECISION NOT NULL,
    payload_json    JSONB,
    mes_row_hash    VARCHAR(64),
    CONSTRAINT ck_mes_operating_event_kind
        CHECK (event_kind IN ('HOLD', 'RELEASE', 'SCRAP', 'REWORK'))
);

CREATE INDEX IF NOT EXISTS ix_mes_operating_scenario_time
    ON mes_operating_event (scenario_id, scheduled_time);

-- ---------------------------------------------------------------------------
-- 7) mes_wip_snapshot: optional columns for restore
-- ---------------------------------------------------------------------------
ALTER TABLE mes_wip_snapshot
    ADD COLUMN IF NOT EXISTS product VARCHAR(128),
    ADD COLUMN IF NOT EXISTS is_super_hot BOOLEAN NOT NULL DEFAULT FALSE;

-- ---------------------------------------------------------------------------
-- 8) Views: WHAT-IF vs baseline KPI diff (optional analytics)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_mes_scenario_run_pair AS
SELECT
    b.scenario_id AS baseline_scenario_id,
    w.scenario_id AS whatif_scenario_id,
    br.simulation_run_id AS baseline_run_id,
    wr.simulation_run_id AS whatif_run_id
FROM mes_scenario w
JOIN mes_scenario b ON b.scenario_id = w.baseline_scenario_id
LEFT JOIN mes_scenario_run wr ON wr.scenario_id = w.scenario_id
LEFT JOIN mes_scenario_run br ON br.scenario_id = b.scenario_id
WHERE w.mode = 'WHATIF';

COMMENT ON TABLE mes_forward_input_event IS 'Sparse forward inputs: HOLD/RELEASE/FAB_ARRIVAL (not full TRACK_IN grid)';
COMMENT ON TABLE mes_lot_release_plan IS 'Lot releases in [t0, t0+horizon] for FORWARD simulation';
COMMENT ON TABLE mes_whatif_action IS 'Agent/operator overrides for WHAT-IF mode';
COMMENT ON TABLE mes_operating_event IS 'Optional MES operating calendar (SCRAP/REWORK/HOLD)';
