-- Example: T0=10800 (180h), horizon=180min, 3 lots, 2 tools (Litho_FE#1, Litho_FE#2)
-- Requires master routes/steps to exist for route_id used (adjust route_id to your DB).

INSERT INTO mes_scenario (
    scenario_id, description, source_system, mes_extract_batch_id,
    t0_sim_minute, horizon_minutes, mode, status, created_by
) VALUES (
    'MES_DEMO_180',
    'Demo replay: 3 lots, Litho_FE#1/#2, 180min window',
    'MES_POC',
    'BATCH_20240522_001',
    10800.0,
    180.0,
    'REPLAY',
    'VALIDATED',
    'seed'
) ON CONFLICT (scenario_id) DO NOTHING;

-- T0 WIP: one lot already queuing on Litho_FE#1
INSERT INTO mes_wip_snapshot (
    scenario_id, snapshot_time, lot_id, route_id, current_step_seq, status,
    tool_group, tool_id, queue_position, due_date_sim, priority, rem_steps, wafers_per_lot
) VALUES (
    'MES_DEMO_180', 10800.0, 'Lot_Demo_A', 'Route_Product_E3', 100, 'QUEUING',
    'Litho_FE', 'Litho_FE#1', 1, 11200.0, 10, 50, 25
) ON CONFLICT (scenario_id, lot_id) DO NOTHING;

INSERT INTO mes_tool_snapshot (scenario_id, tool_id, tool_group, op_state, current_setup, held_lot_id)
VALUES
    ('MES_DEMO_180', 'Litho_FE#1', 'Litho_FE', 'IDLE', 'SU128_1', NULL),
    ('MES_DEMO_180', 'Litho_FE#2', 'Litho_FE', 'RUN', 'SU128_1', 'Lot_Demo_B')
ON CONFLICT (scenario_id, tool_id) DO NOTHING;

INSERT INTO mes_tool_queue_snapshot (scenario_id, tool_id, position, lot_id, route_id, step_seq, due_date_sim, priority)
VALUES ('MES_DEMO_180', 'Litho_FE#1', 1, 'Lot_Demo_A', 'Route_Product_E3', 100, 11200.0, 10)
ON CONFLICT (scenario_id, tool_id, position) DO NOTHING;

-- Planned events in (10800, 10980]
INSERT INTO mes_schedule_event (
    scenario_id, seq, lot_id, product, route_id, step_seq, step_name,
    tool_group, tool_id, event_kind, scheduled_time, scheduled_arrive_time, scheduled_end_time,
    proc_time_planned, priority, due_date_sim, wafers_per_lot, mes_row_hash, source_line_no
) VALUES
    ('MES_DEMO_180', 0, 'Lot_Demo_A', 'Product_3', 'Route_Product_E3', 100, '100_Litho',
     'Litho_FE', 'Litho_FE#1', 'TRACK_IN', 10805.0, 10800.0, 10845.0, 40.0, 10, 11200.0, 25, 'a100ti', 1),
    ('MES_DEMO_180', 0, 'Lot_Demo_B', 'Product_3', 'Route_Product_E3', 100, '100_Litho',
     'Litho_FE', 'Litho_FE#2', 'TRACK_OUT', 10820.0, NULL, 10820.0, NULL, 10, 11150.0, 25, 'b100to', 2),
    ('MES_DEMO_180', 0, 'Lot_Demo_C', 'Product_3', 'Route_Product_E3', 100, '100_Litho',
     'Litho_FE', 'Litho_FE#2', 'TRACK_IN', 10825.0, 10822.0, 10865.0, 40.0, 20, 11300.0, 25, 'c100ti', 3),
    ('MES_DEMO_180', 0, 'Lot_Demo_A', 'Product_3', 'Route_Product_E3', 200, '200_Etch',
     'Wet_Etch', 'Wet_Etch#1', 'TRACK_IN', 10890.0, 10850.0, 10920.0, 30.0, 10, 11200.0, 25, 'a200ti', 4)
ON CONFLICT DO NOTHING;
