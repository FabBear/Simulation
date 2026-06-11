# MES scenario bundles (FORWARD / WHAT-IF)

## Layout

| File | FORWARD | WHAT-IF |
|------|---------|---------|
| `mes_tool_snapshot.csv` | T0 tool state | **same as baseline** (copy) |
| `mes_tool_queue_snapshot.csv` | T0 queues | **same** |
| `mes_wip_snapshot.csv` | T0 WIP | **same** (or optional diff) |
| `mes_lot_release_plan.csv` | baseline plan | **plan diff** |
| `mes_whatif_action.csv` | — | ≥4 actions |
| `mes_scenario.meta.json` | `mode=FORWARD` | `mode=WHATIF`, `baseline_scenario_id` |

## Generate baseline

```bash
cd FAB_BEAR/simulation
.venv/bin/python tools/build_forward_scenario_from_csv.py \
  --run-id <ref_run> --t0 <T0> --horizon 120 \
  --scenario-id FWD_BASE_<tag> --sim-csv-dir sim_csv_out
```

## Build what-if bundle

```bash
.venv/bin/python tools/make_whatif_scenario_bundle.py \
  --base-dir scenario_out/FWD_BASE_<tag> \
  --whatif-scenario-id FWD_WHATIF_<tag> \
  --baseline-scenario-id FWD_BASE_<tag> \
  --t0 <T0> --horizon 120 \
  --whatif-actions scenario_out/_templates/mes_whatif_action_p0.csv
```

## Load, promote, run, compare

See `FWD_BASE_SAMPLE/LOAD_COMMAND.txt` and `docs/MES_WHATIF_ACTION.md`.

`FWD_*_SAMPLE` directories are **layout templates**; replace with real `build_forward_scenario_from_csv` output before DB load.
