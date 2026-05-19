INSERT INTO toolgroup (
    toolgroup_name, num_tools, location, is_cascading, is_batching,
    batch_criterion, batch_unit, loading_time, unloading_time,
    dispatch_rule, ranking_1, ranking_2, ranking_3
)
SELECT
    'ETCH', 2, 'FAB_A', FALSE, FALSE,
    NULL, NULL, 1.0, 1.0,
    'FIFO', 'priority', 'due_date', 'rem_steps'
WHERE NOT EXISTS (SELECT 1 FROM toolgroup WHERE toolgroup_name = 'ETCH');

INSERT INTO toolgroup (
    toolgroup_name, num_tools, location, is_cascading, is_batching,
    batch_criterion, batch_unit, loading_time, unloading_time,
    dispatch_rule, ranking_1, ranking_2, ranking_3
)
SELECT
    'PHOTO', 1, 'FAB_A', FALSE, FALSE,
    NULL, NULL, 1.0, 1.0,
    'FIFO', 'priority', 'due_date', 'rem_steps'
WHERE NOT EXISTS (SELECT 1 FROM toolgroup WHERE toolgroup_name = 'PHOTO');

INSERT INTO process_step (
    route_id, step_seq, step_name, area, target_tool_group, proc_unit,
    proc_time_dist, proc_time_mean, proc_time_offset, proc_time_unit,
    cascading_interval, batch_min, batch_max, setup_id, setup_policy,
    setup_time_mean, setup_time_offset, ltl_dedication_step, rework_prob,
    rework_target_step, sampling_prob, cqt_start_step, cqt_limit, cqt_unit
)
SELECT
    'Route_Product_E3', 1, 'ETCH_MAIN', 'ETCH', 'ETCH', 'LOT',
    'CONST', 4.0, 0.0, 'min',
    NULL, NULL, NULL, NULL, NULL,
    NULL, NULL, NULL, 0.0,
    NULL, 100.0, NULL, NULL, NULL
WHERE NOT EXISTS (
    SELECT 1 FROM process_step WHERE route_id = 'Route_Product_E3' AND step_seq = 1
);

INSERT INTO process_step (
    route_id, step_seq, step_name, area, target_tool_group, proc_unit,
    proc_time_dist, proc_time_mean, proc_time_offset, proc_time_unit,
    cascading_interval, batch_min, batch_max, setup_id, setup_policy,
    setup_time_mean, setup_time_offset, ltl_dedication_step, rework_prob,
    rework_target_step, sampling_prob, cqt_start_step, cqt_limit, cqt_unit
)
SELECT
    'Route_Product_E4', 1, 'PHOTO_MAIN', 'PHOTO', 'PHOTO', 'LOT',
    'CONST', 3.0, 0.0, 'min',
    NULL, NULL, NULL, NULL, NULL,
    NULL, NULL, NULL, 0.0,
    NULL, 100.0, NULL, NULL, NULL
WHERE NOT EXISTS (
    SELECT 1 FROM process_step WHERE route_id = 'Route_Product_E4' AND step_seq = 1
);

INSERT INTO lot_release (
    product_name, route_name, lot_type, priority, is_super_hot_lot, wafers_per_lot,
    start_date, due_date, release_dist, release_interval, release_unit, lots_per_release
)
SELECT
    'Product_3', 'Route_Product_E3', 'NORMAL', 10, 'N', 25,
    '0', '1000', 'CONST', 1.0, 'min', 1
WHERE NOT EXISTS (
    SELECT 1 FROM lot_release WHERE product_name = 'Product_3' AND route_name = 'Route_Product_E3'
);

INSERT INTO lot_release (
    product_name, route_name, lot_type, priority, is_super_hot_lot, wafers_per_lot,
    start_date, due_date, release_dist, release_interval, release_unit, lots_per_release
)
SELECT
    'Product_4', 'Route_Product_E4', 'NORMAL', 8, 'N', 25,
    '0', '900', 'CONST', 2.0, 'min', 1
WHERE NOT EXISTS (
    SELECT 1 FROM lot_release WHERE product_name = 'Product_4' AND route_name = 'Route_Product_E4'
);
