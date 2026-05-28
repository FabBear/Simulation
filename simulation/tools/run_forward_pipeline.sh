#!/usr/bin/env bash
# Build MES scenario from sim_csv_out, load DB, promote VALIDATED, run forward once.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

RUN_ID="${1:?run_id}"
T0="${2:?t0_abs_minute}"
HORIZON="${3:-180}"
SCENARIO_ID="${4:-FWD_FROM_${RUN_ID}_T${T0}}"
SIM_CSV_DIR="${5:-$ROOT/sim_csv_out}"

export DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5433/postgres}"

PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -q sqlalchemy psycopg2-binary pandas openpyxl gym simpy numpy
  PY="${ROOT}/.venv/bin/python"
fi

OUT="$ROOT/scenario_out/$SCENARIO_ID"
"$PY" tools/build_forward_scenario_from_csv.py \
  --run-id "$RUN_ID" --t0 "$T0" --horizon "$HORIZON" \
  --scenario-id "$SCENARIO_ID" --sim-csv-dir "$SIM_CSV_DIR"

"$PY" load_mes_scenario.py --create-tables \
  --scenario-id "$SCENARIO_ID" --t0 "$T0" --horizon "$HORIZON" \
  --description "CSV reverse-engineered @ T0=$T0" \
  --tools "$OUT/mes_tool_snapshot.csv" \
  --queues "$OUT/mes_tool_queue_snapshot.csv" \
  --wip "$OUT/mes_wip_snapshot.csv" \
  --releases "$OUT/mes_lot_release_plan.csv"

"$PY" tools/promote_scenario_validated.py --scenario-id "$SCENARIO_ID"

export SIM_CSV_DIR="${SIM_CSV_DIR:-$ROOT/sim_csv_out}"
"$PY" run_sim_forward_once.py --scenario-id "$SCENARIO_ID"

echo "OK scenario=$SCENARIO_ID bundle=$OUT"
