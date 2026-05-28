-- MES FORWARD / WHAT-IF validation queries
-- Replace :scenario_id with actual id (e.g. FWD_001)

-- 1) Scenario window
SELECT scenario_id, mode, t0_sim_minute, horizon_minutes,
       t0_sim_minute + horizon_minutes AS t_end,
       baseline_scenario_id, use_master_lot_release
FROM mes_scenario
WHERE scenario_id = :'scenario_id';

-- 2) WIP snapshot time = T0
SELECT w.lot_id, w.snapshot_time, s.t0_sim_minute,
       ABS(w.snapshot_time - s.t0_sim_minute) AS delta_min
FROM mes_wip_snapshot w
JOIN mes_scenario s ON s.scenario_id = w.scenario_id
WHERE w.scenario_id = :'scenario_id'
  AND ABS(w.snapshot_time - s.t0_sim_minute) > 0.001;

-- 3) Releases inside [t0, t0+x]
SELECT r.id, r.release_time, s.t0_sim_minute, s.t0_sim_minute + s.horizon_minutes AS t_end
FROM mes_lot_release_plan r
JOIN mes_scenario s ON s.scenario_id = r.scenario_id
WHERE r.scenario_id = :'scenario_id'
  AND (r.release_time < s.t0_sim_minute
       OR r.release_time > s.t0_sim_minute + s.horizon_minutes);

-- 4) Forward input events inside window
SELECT e.id, e.event_kind, e.scheduled_time
FROM mes_forward_input_event e
JOIN mes_scenario s ON s.scenario_id = e.scenario_id
WHERE e.scenario_id = :'scenario_id'
  AND (e.scheduled_time < s.t0_sim_minute
       OR e.scheduled_time > s.t0_sim_minute + s.horizon_minutes);

-- 5) WHAT-IF must have actions
SELECT COUNT(*) AS whatif_action_count
FROM mes_whatif_action
WHERE scenario_id = :'scenario_id';

-- 6) WHAT-IF must reference baseline
SELECT scenario_id, mode, baseline_scenario_id
FROM mes_scenario
WHERE scenario_id = :'scenario_id'
  AND mode = 'WHATIF'
  AND baseline_scenario_id IS NULL;

-- 7) process_step exists for WIP lots
SELECT DISTINCT w.lot_id, w.route_id, w.current_step_seq
FROM mes_wip_snapshot w
LEFT JOIN process_step ps
  ON ps.route_id = w.route_id AND ps.step_seq = w.current_step_seq
WHERE w.scenario_id = :'scenario_id'
  AND ps.route_id IS NULL;

-- 8) tool_id in range (WIP)
SELECT w.lot_id, w.tool_id, w.tool_group
FROM mes_wip_snapshot w
JOIN mes_scenario s ON s.scenario_id = w.scenario_id
WHERE w.scenario_id = :'scenario_id'
  AND w.tool_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM toolgroup tg
    WHERE tg.toolgroup_name = w.tool_group
      AND CAST(SUBSTRING(w.tool_id FROM '#([0-9]+)$') AS INTEGER)
          BETWEEN 1 AND GREATEST(1, COALESCE(tg.num_tools, 1))
  );

-- 9) No deprecated TRACK_IN rows (should return 0 rows)
SELECT COUNT(*) AS deprecated_schedule_rows
FROM _archive_mes_schedule_replay a
WHERE a.scenario_id = :'scenario_id'
  AND a.event_kind = 'TRACK_IN';

-- 10) WHAT-IF effective times in window
SELECT a.id, a.action_kind, a.effective_time
FROM mes_whatif_action a
JOIN mes_scenario s ON s.scenario_id = a.scenario_id
WHERE a.scenario_id = :'scenario_id'
  AND (a.effective_time < s.t0_sim_minute
       OR a.effective_time > s.t0_sim_minute + s.horizon_minutes);
