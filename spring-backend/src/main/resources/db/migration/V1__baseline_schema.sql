CREATE TABLE IF NOT EXISTS toolgroup (
    toolgroup_name VARCHAR PRIMARY KEY,
    num_tools INTEGER,
    location VARCHAR,
    is_cascading BOOLEAN DEFAULT FALSE,
    is_batching BOOLEAN DEFAULT FALSE,
    batch_criterion VARCHAR,
    batch_unit VARCHAR,
    loading_time DOUBLE PRECISION DEFAULT 0.0,
    unloading_time DOUBLE PRECISION DEFAULT 0.0,
    dispatch_rule VARCHAR,
    ranking_1 VARCHAR,
    ranking_2 VARCHAR,
    ranking_3 VARCHAR
);

CREATE TABLE IF NOT EXISTS process_step (
    route_id VARCHAR NOT NULL,
    step_seq INTEGER NOT NULL,
    step_name VARCHAR,
    area VARCHAR,
    target_tool_group VARCHAR,
    proc_unit VARCHAR,
    proc_time_dist VARCHAR,
    proc_time_mean DOUBLE PRECISION,
    proc_time_offset DOUBLE PRECISION,
    proc_time_unit VARCHAR,
    cascading_interval DOUBLE PRECISION,
    batch_min INTEGER,
    batch_max INTEGER,
    setup_id VARCHAR,
    setup_policy VARCHAR,
    setup_time_mean DOUBLE PRECISION,
    setup_time_offset DOUBLE PRECISION,
    ltl_dedication_step INTEGER,
    rework_prob DOUBLE PRECISION,
    rework_target_step INTEGER,
    sampling_prob DOUBLE PRECISION DEFAULT 100.0,
    cqt_start_step INTEGER,
    cqt_limit DOUBLE PRECISION,
    cqt_unit VARCHAR,
    PRIMARY KEY (route_id, step_seq)
);

CREATE TABLE IF NOT EXISTS pm_event (
    id SERIAL PRIMARY KEY,
    pm_name VARCHAR,
    target_tool_group VARCHAR,
    pm_type VARCHAR,
    mtbf DOUBLE PRECISION,
    mtbf_unit VARCHAR,
    duration_mean DOUBLE PRECISION,
    duration_offset DOUBLE PRECISION,
    duration_unit VARCHAR,
    first_occurrence DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS breakdown_event (
    id SERIAL PRIMARY KEY,
    event_name VARCHAR,
    scope VARCHAR,
    target_name VARCHAR,
    ttf_dist VARCHAR,
    mttf_mean DOUBLE PRECISION,
    mttf_unit VARCHAR,
    ttr_dist VARCHAR,
    mttr_mean DOUBLE PRECISION,
    mttr_unit VARCHAR,
    foa_dist VARCHAR,
    foa_mean DOUBLE PRECISION,
    foa_unit VARCHAR
);

CREATE TABLE IF NOT EXISTS lot_release (
    id SERIAL PRIMARY KEY,
    product_name VARCHAR,
    route_name VARCHAR,
    lot_type VARCHAR,
    priority INTEGER,
    is_super_hot_lot VARCHAR,
    wafers_per_lot INTEGER,
    start_date VARCHAR,
    due_date VARCHAR,
    release_dist VARCHAR,
    release_interval DOUBLE PRECISION,
    release_unit VARCHAR,
    lots_per_release INTEGER
);

CREATE TABLE IF NOT EXISTS setup_info_final (
    id SERIAL PRIMARY KEY,
    setup_group VARCHAR,
    from_setup VARCHAR,
    to_setup VARCHAR,
    setup_time DOUBLE PRECISION,
    setup_unit VARCHAR,
    min_run_length INTEGER
);

CREATE TABLE IF NOT EXISTS transport_time (
    id SERIAL PRIMARY KEY,
    from_loc VARCHAR,
    to_loc VARCHAR,
    dist_type VARCHAR,
    mean_time DOUBLE PRECISION,
    offset_time DOUBLE PRECISION,
    time_unit VARCHAR
);

CREATE TABLE IF NOT EXISTS simulation_log (
    id SERIAL PRIMARY KEY,
    lot_id VARCHAR,
    product VARCHAR,
    route_id VARCHAR,
    step_seq INTEGER,
    step_name VARCHAR,
    tool_group VARCHAR,
    arrive_time DOUBLE PRECISION,
    start_time DOUBLE PRECISION,
    end_time DOUBLE PRECISION,
    queue_time DOUBLE PRECISION,
    process_time DOUBLE PRECISION,
    event_type VARCHAR
);
