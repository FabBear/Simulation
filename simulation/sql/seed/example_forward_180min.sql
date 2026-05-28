-- Example FORWARD scenario: T0=10800, horizon=180min
-- Adjust route_id / tool_group to match your init_db master data.

INSERT INTO mes_scenario (
    scenario_id, description, source_system, t0_sim_minute, horizon_minutes,
    mode, status, trigger_meta, use_master_lot_release, created_by
) VALUES (
    'FWD_DEMO_180',
    'Forward demo: T0 snapshot + releases in window',
    'MES_POC',
    10800.0,
    180.0,
    'FORWARD',
    'VALIDATED',
    '{"trigger_tg": "Litho_FE", "snapshot_time": 10800, "model": "xgb"}'::jsonb,
    false,
    'seed'
) ON CONFLICT (scenario_id) DO UPDATE SET
    mode = EXCLUDED.mode,
    t0_sim_minute = EXCLUDED.t0_sim_minute,
    horizon_minutes = EXCLUDED.horizon_minutes;

DELETE FROM mes_wip_snapshot WHERE scenario_id = 'FWD_DEMO_180';
DELETE FROM mes_tool_snapshot WHERE scenario_id = 'FWD_DEMO_180';
DELETE FROM mes_tool_queue_snapshot WHERE scenario_id = 'FWD_DEMO_180';
DELETE FROM mes_lot_release_plan WHERE scenario_id = 'FWD_DEMO_180';

INSERT INTO mes_wip_snapshot (
    scenario_id, snapshot_time, lot_id, route_id, current_step_seq, status,
    tool_group, tool_id, queue_position, due_date_sim, priority, rem_steps, wafers_per_lot
) VALUES (
    'FWD_DEMO_180', 10800.0, 'Lot_Demo_A', 'Route_Product_E3', 100, 'QUEUING',
    'Litho_FE', 'Litho_FE#1', 1, 11200.0, 10, 50, 25
);

INSERT INTO mes_tool_snapshot (scenario_id, tool_id, tool_group, op_state, current_setup, held_lot_id)
VALUES
    ('FWD_DEMO_180', 'Litho_FE#1', 'Litho_FE', 'IDLE', 'SU128_1', NULL),
    ('FWD_DEMO_180', 'Litho_FE#2', 'Litho_FE', 'RUN', 'SU128_1', 'Lot_Demo_B');

INSERT INTO mes_tool_queue_snapshot (scenario_id, tool_id, position, lot_id, route_id, step_seq, due_date_sim, priority)
VALUES ('FWD_DEMO_180', 'Litho_FE#1', 1, 'Lot_Demo_A', 'Route_Product_E3', 100, 11200.0, 10);

-- Release inside [10800, 10980]
INSERT INTO mes_lot_release_plan (
    scenario_id, product_name, route_name, release_time, lots_count,
    priority, due_date_sim, wafers_per_lot, mes_row_hash
) VALUES (
    'FWD_DEMO_180', 'Product_3', 'Route_Product_E3', 10860.0, 1,
    20, 11100.0, 25, 'rel_10860_1'
);

-- WHAT-IF child scenario
INSERT INTO mes_scenario (
    scenario_id, description, t0_sim_minute, horizon_minutes,
    mode, baseline_scenario_id, status, created_by
) VALUES (
    'WHATIF_DEMO_180',
    'What-if: raise priority on Lot_Demo_A',
    10800.0,
    180.0,
    'WHATIF',
    'FWD_DEMO_180',
    'DRAFT',
    'seed'
) ON CONFLICT (scenario_id) DO NOTHING;

DELETE FROM mes_whatif_action WHERE scenario_id = 'WHATIF_DEMO_180';

INSERT INTO mes_whatif_action (
    scenario_id, seq, action_kind, effective_time, lot_id, payload_json, source
) VALUES (
    'WHATIF_DEMO_180', 1, 'LOT_PRIORITY', 10805.0, 'Lot_Demo_A',
    '{"priority": 1}'::jsonb, 'AGENT'
);
