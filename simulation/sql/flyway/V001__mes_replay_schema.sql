-- Platform SSOT schema (POSTGRES_SCHEMA=simulation)
CREATE SCHEMA IF NOT EXISTS simulation;
SET search_path TO simulation;


-- FAB_BEAR MES schedule REPLAY input schema
-- Apply after master tables (toolgroup, process_step, ...) exist.
-- FabEnv: DISPATCH_MODE=mes_replay (future) reads mes_* tables; does not use lot_release.

-- ---------------------------------------------------------------------------
-- 1) mes_scenario
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mes_scenario (
    scenario_id           VARCHAR(64) PRIMARY KEY,
    description           TEXT,
    source_system         VARCHAR(128),
    mes_extract_batch_id  VARCHAR(128),
    t0_sim_minute         DOUBLE PRECISION NOT NULL,
    horizon_minutes       DOUBLE PRECISION NOT NULL,
    sim_start_calendar    DATE,
    mode                  VARCHAR(32) NOT NULL DEFAULT 'REPLAY',
    master_snapshot_hash  VARCHAR(64),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by            VARCHAR(128),
    status                VARCHAR(32) NOT NULL DEFAULT 'DRAFT',
    CONSTRAINT ck_mes_scenario_mode
        CHECK (mode IN ('REPLAY', 'REPLAY_WHATIF')),
    CONSTRAINT ck_mes_scenario_status
        CHECK (status IN ('DRAFT', 'VALIDATED', 'RUNNING', 'DONE')),
    CONSTRAINT ck_mes_scenario_horizon
        CHECK (horizon_minutes > 0)
);

CREATE INDEX IF NOT EXISTS ix_mes_scenario_status ON mes_scenario (status);
CREATE INDEX IF NOT EXISTS ix_mes_scenario_t0 ON mes_scenario (t0_sim_minute);

-- ---------------------------------------------------------------------------
-- 2) mes_schedule_event (core)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mes_schedule_event (
    id                    BIGSERIAL PRIMARY KEY,
    scenario_id           VARCHAR(64) NOT NULL REFERENCES mes_scenario (scenario_id) ON DELETE CASCADE,
    seq                   INTEGER NOT NULL DEFAULT 0,
    lot_id                VARCHAR(128) NOT NULL,
    product               VARCHAR(128),
    route_id              VARCHAR(128) NOT NULL,
    step_seq              INTEGER NOT NULL,
    step_name             VARCHAR(256),
    tool_group            VARCHAR(128),
    tool_id               VARCHAR(128),
    event_kind            VARCHAR(32) NOT NULL,
    scheduled_time        DOUBLE PRECISION NOT NULL,
    scheduled_arrive_time DOUBLE PRECISION,
    scheduled_end_time    DOUBLE PRECISION,
    proc_time_planned     DOUBLE PRECISION,
    setup_id              VARCHAR(128),
    priority              INTEGER,
    due_date_sim          DOUBLE PRECISION,
    wafers_per_lot        INTEGER,
    is_frozen             BOOLEAN NOT NULL DEFAULT TRUE,
    mes_row_hash          VARCHAR(64),
    source_line_no        INTEGER,
    CONSTRAINT ck_mes_schedule_event_kind
        CHECK (event_kind IN (
            'ARRIVE_QUEUE', 'TRACK_IN', 'TRACK_OUT',
            'TRANSPORT_START', 'HOLD', 'RELEASE'
        )),
    CONSTRAINT ck_mes_schedule_tool_id_format
        CHECK (tool_id IS NULL OR tool_id ~ '^[^#]+#[1-9][0-9]*$')
);

-- One TRACK_IN per (scenario, lot, step); other kinds may repeat (HOLD/RELEASE).
CREATE UNIQUE INDEX IF NOT EXISTS uq_mes_schedule_track_in
    ON mes_schedule_event (scenario_id, lot_id, step_seq)
    WHERE event_kind = 'TRACK_IN';

CREATE UNIQUE INDEX IF NOT EXISTS uq_mes_schedule_row_hash
    ON mes_schedule_event (scenario_id, mes_row_hash)
    WHERE mes_row_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_mes_schedule_scenario_time
    ON mes_schedule_event (scenario_id, scheduled_time);

CREATE INDEX IF NOT EXISTS ix_mes_schedule_scenario_tool_time
    ON mes_schedule_event (scenario_id, tool_id, scheduled_time);

CREATE INDEX IF NOT EXISTS ix_mes_schedule_scenario_lot
    ON mes_schedule_event (scenario_id, lot_id);

-- ---------------------------------------------------------------------------
-- 3) mes_wip_snapshot (T0 WIP)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mes_wip_snapshot (
    id                      BIGSERIAL PRIMARY KEY,
    scenario_id             VARCHAR(64) NOT NULL REFERENCES mes_scenario (scenario_id) ON DELETE CASCADE,
    snapshot_time           DOUBLE PRECISION NOT NULL,
    lot_id                  VARCHAR(128) NOT NULL,
    route_id                VARCHAR(128) NOT NULL,
    current_step_seq        INTEGER NOT NULL,
    status                  VARCHAR(32) NOT NULL,
    tool_group              VARCHAR(128),
    tool_id                 VARCHAR(128),
    queue_position          INTEGER,
    due_date_sim            DOUBLE PRECISION,
    priority                INTEGER,
    rem_steps               INTEGER,
    processing_remaining_min DOUBLE PRECISION,
    wafers_per_lot          INTEGER,
    CONSTRAINT ck_mes_wip_status
        CHECK (status IN (
            'QUEUING', 'PROCESSING', 'WAIT_TRANSPORT', 'HOLD', 'WAIT_BATCH'
        )),
    CONSTRAINT ck_mes_wip_tool_id_format
        CHECK (tool_id IS NULL OR tool_id ~ '^[^#]+#[1-9][0-9]*$'),
    CONSTRAINT uq_mes_wip_lot UNIQUE (scenario_id, lot_id)
);

CREATE INDEX IF NOT EXISTS ix_mes_wip_scenario ON mes_wip_snapshot (scenario_id);

-- ---------------------------------------------------------------------------
-- 4) mes_tool_snapshot (T0 tool state)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mes_tool_snapshot (
    id              BIGSERIAL PRIMARY KEY,
    scenario_id     VARCHAR(64) NOT NULL REFERENCES mes_scenario (scenario_id) ON DELETE CASCADE,
    tool_id         VARCHAR(128) NOT NULL,
    tool_group      VARCHAR(128) NOT NULL,
    op_state        VARCHAR(32) NOT NULL,
    current_setup   VARCHAR(128),
    held_lot_id     VARCHAR(128),
    CONSTRAINT ck_mes_tool_op_state
        CHECK (op_state IN ('IDLE', 'RUN', 'SETUP', 'DOWN_PM', 'DOWN_BM')),
    CONSTRAINT ck_mes_tool_snapshot_tool_id_format
        CHECK (tool_id ~ '^[^#]+#[1-9][0-9]*$'),
    CONSTRAINT uq_mes_tool_snapshot UNIQUE (scenario_id, tool_id)
);

-- ---------------------------------------------------------------------------
-- 5) mes_tool_queue_snapshot (optional, ordered queue at T0)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mes_tool_queue_snapshot (
    id              BIGSERIAL PRIMARY KEY,
    scenario_id     VARCHAR(64) NOT NULL REFERENCES mes_scenario (scenario_id) ON DELETE CASCADE,
    tool_id         VARCHAR(128) NOT NULL,
    position        INTEGER NOT NULL,
    lot_id          VARCHAR(128) NOT NULL,
    route_id        VARCHAR(128),
    step_seq        INTEGER,
    due_date_sim    DOUBLE PRECISION,
    priority        INTEGER,
    CONSTRAINT ck_mes_tool_queue_tool_id_format
        CHECK (tool_id ~ '^[^#]+#[1-9][0-9]*$'),
    CONSTRAINT uq_mes_tool_queue_pos UNIQUE (scenario_id, tool_id, position)
);

CREATE INDEX IF NOT EXISTS ix_mes_tool_queue_tool
    ON mes_tool_queue_snapshot (scenario_id, tool_id);

-- ---------------------------------------------------------------------------
-- 6) mes_cqt_snapshot (optional)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mes_cqt_snapshot (
    id              BIGSERIAL PRIMARY KEY,
    scenario_id     VARCHAR(64) NOT NULL REFERENCES mes_scenario (scenario_id) ON DELETE CASCADE,
    lot_id          VARCHAR(128) NOT NULL,
    anchor_step     INTEGER,
    target_step     INTEGER NOT NULL,
    deadline_time   DOUBLE PRECISION NOT NULL,
    started_at      DOUBLE PRECISION NOT NULL,
    CONSTRAINT uq_mes_cqt_lot UNIQUE (scenario_id, lot_id)
);

-- ---------------------------------------------------------------------------
-- 7) mes_scenario_run (execution history → simulation_run)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mes_scenario_run (
    id                  BIGSERIAL PRIMARY KEY,
    scenario_id         VARCHAR(64) NOT NULL REFERENCES mes_scenario (scenario_id) ON DELETE CASCADE,
    simulation_run_id   VARCHAR(64) NOT NULL REFERENCES simulation_run (run_id) ON DELETE CASCADE,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at         TIMESTAMPTZ,
    validation_report   JSONB,
    CONSTRAINT uq_mes_scenario_run UNIQUE (scenario_id, simulation_run_id)
);

CREATE INDEX IF NOT EXISTS ix_mes_scenario_run_scenario ON mes_scenario_run (scenario_id);

-- ---------------------------------------------------------------------------
-- View: schedule vs actual (no change to simulation_log)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_schedule_adherence AS
SELECT
    m.scenario_id,
    r.simulation_run_id AS run_id,
    m.lot_id,
    m.route_id,
    m.step_seq,
    m.event_kind,
    m.tool_group AS planned_tool_group,
    m.tool_id AS planned_tool_id,
    m.scheduled_time AS planned_time,
    m.scheduled_end_time AS planned_end_time,
    s.tool_group AS actual_tool_group,
    s.tool_id AS actual_tool_id,
    s.start_time AS actual_start_time,
    s.end_time AS actual_end_time,
    (s.start_time - m.scheduled_time) AS start_delta_min,
    (s.end_time - m.scheduled_end_time) AS end_delta_min,
    CASE
        WHEN s.id IS NULL THEN 'MISSING'
        WHEN m.tool_id IS NOT NULL AND s.tool_id IS DISTINCT FROM m.tool_id THEN 'TOOL_MISMATCH'
        WHEN ABS(s.start_time - m.scheduled_time) > 1.0 THEN 'LATE'
        ELSE 'OK'
    END AS adherence_status
FROM mes_schedule_event m
JOIN mes_scenario_run r ON r.scenario_id = m.scenario_id
LEFT JOIN simulation_log s
    ON s.run_id = r.simulation_run_id
   AND s.lot_id = m.lot_id
   AND s.route_id = m.route_id
   AND s.step_seq = m.step_seq
WHERE m.event_kind = 'TRACK_IN';

COMMENT ON TABLE mes_scenario IS 'MES replay scenario metadata (T0, horizon, mode)';
COMMENT ON TABLE mes_schedule_event IS 'Planned lot/step/tool/timing from MES; FabEnv mes_replay dispatch source';
COMMENT ON VIEW v_schedule_adherence IS 'Compare planned TRACK_IN vs simulation_log actuals per run';
