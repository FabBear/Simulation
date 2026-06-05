#!/usr/bin/env bash
# ML @ T0 → G* (+ SHAP audit) → FORWARD N× → G* KPI analysis (root_cause Agent)
#
# Usage (from repo root or simulation/):
#   cd FAB_BEAR/simulation
#   chmod +x tools/run_ml_g_star_e2e.sh
#   ./tools/run_ml_g_star_e2e.sh
#
# Env overrides:
#   T0=26820 N_RUNS=30 PARALLEL=6 ALARM_THR=0.7 SNAPSHOT_STRIDE=10
#   SKIP_ML=1 SKIP_SIM=1  (reuse prior out artifacts)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f ../.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source ../.env
  set +a
fi

PY="${PY:-$ROOT/.venv/bin/python}"
T0="${T0:-26820}"
HORIZON="${HORIZON:-120}"
N_RUNS="${N_RUNS:-5}"
PARALLEL="${PARALLEL:-4}"
ALARM_THR="${ALARM_THR:-0.7}"
SNAPSHOT_STRIDE="${SNAPSHOT_STRIDE:-10}"
SCENARIO_ID="${SCENARIO_ID:-FWD_BASE_T26820}"
OUT_DIR="${OUT_DIR:-$ROOT/out/ml_g_star_e2e}"
TRAIN_CSV="${TRAIN_CSV:-$ROOT/sim_csv_out}"
INFER_CSV="${INFER_CSV:-$ROOT/sim_csv_out}"

mkdir -p "$OUT_DIR"

echo "========== [1/5] ML train + G* @ T0 =========="
if [[ "${SKIP_ML:-0}" != "1" ]]; then
  "$PY" tools/ml_g_star_at_t0.py \
    --train-csv-dir "$TRAIN_CSV" \
    --inference-csv-dir "$INFER_CSV" \
    --t0 "$T0" \
    --horizon "$HORIZON" \
    --out-dir "$OUT_DIR" \
    --alarm-threshold "$ALARM_THR" \
    --snapshot-stride "$SNAPSHOT_STRIDE" \
    --shap-top-k 5
else
  echo "SKIP_ML=1 — reuse $OUT_DIR/g_star_T${T0}.json"
fi

G_STAR_FILE="$OUT_DIR/g_star_T${T0%.*}.json"
if [[ ! -f "$G_STAR_FILE" ]]; then
  G_STAR_FILE="$OUT_DIR/g_star_T${T0}.json"
fi
if [[ ! -f "$G_STAR_FILE" ]]; then
  echo "ERROR: missing G* file under $OUT_DIR" >&2
  exit 1
fi

ANCHOR_TG="$("$PY" -c "
import json
from pathlib import Path
p = Path('$G_STAR_FILE')
d = json.loads(p.read_text())
print(d.get('anchor_tg') or (d['toolgroups'][0] if d.get('toolgroups') else ''))
")"

echo ""
echo "========== [2/5] Audit: G* analysis pool =========="
"$PY" - <<'PY' "$OUT_DIR" "$T0"
import sys
from pathlib import Path
import pandas as pd

out = Path(sys.argv[1])
t0 = sys.argv[2]
audit = out / f"ml_alarm_audit_t{t0}.csv"
if not audit.is_file():
    audit = list(out.glob("ml_alarm_audit_t*.csv"))[0]
df = pd.read_csv(audit)
g = df[df["in_g_star"] == 1]
print(f"audit file: {audit}")
print(f"  total TG: {len(df)}")
print(f"  G* (ML alarm / analysis pool): {len(g)}")
print(f"  bn_t0_rule among G* (diagnostic only): {int((g['bn_t0_rule']==1).sum())}")
print("\n--- G* by proba ---")
print(g.sort_values("proba", ascending=False).to_string(index=False))
PY

echo ""
echo "========== [3/5] FORWARD baseline x${N_RUNS} (seed 1..N) =========="
MANIFEST="$OUT_DIR/runs_manifest.csv"
if [[ "${SKIP_SIM:-0}" != "1" ]]; then
  rm -rf "$OUT_DIR/runs"
  mkdir -p "$OUT_DIR/runs"
  for i in $(seq 1 "$N_RUNS"); do
    RUN_PAD=$(printf '%02d' "$i")
    RUN_DIR="$OUT_DIR/runs/run_${RUN_PAD}"
    echo "--- run $i / $N_RUNS (seed=$i) ---"
    "$PY" tools/promote_scenario_validated.py --scenario-id "$SCENARIO_ID"
    "$PY" run_sim_forward_once.py \
      --scenario-id "$SCENARIO_ID" \
      --seed "$i" \
      --csv-dir "$RUN_DIR"
  done
  "$PY" - <<'PY' "$OUT_DIR" "$N_RUNS" "$SCENARIO_ID"
import sys
from pathlib import Path
from stats.common import RunMeta, write_runs_manifest, _first_run_id

out = Path(sys.argv[1])
n = int(sys.argv[2])
sid = sys.argv[3]
runs = []
for i in range(1, n + 1):
    d = out / "runs" / f"run_{i:02d}"
    runs.append(RunMeta(i, i, d.resolve(), _first_run_id(d), sid, "ok"))
write_runs_manifest(out / "runs_manifest.csv", runs)
print("Wrote", out / "runs_manifest.csv")
PY
else
  echo "SKIP_SIM=1 — reuse $MANIFEST"
fi

echo ""
echo "========== [4/5] G* KPI t-test analysis (historical 2h-diff vs FORWARD) =========="
"$PY" tools/stat_g_star_analysis_report.py \
  --runs-manifest "$MANIFEST" \
  --g-star-file "$G_STAR_FILE" \
  --baseline-csv-dir "$INFER_CSV" \
  --t0 "$T0" \
  --horizon "$HORIZON" \
  --n-runs "$N_RUNS" \
  --anchor-tg "$ANCHOR_TG" \
  --out-dir "$OUT_DIR" \
  --alpha 0.05 \
  --independence-alpha 0.01 \
  --lb-lags 10 \
  --n-diff 30 \
  --multipletest fdr_bh

echo ""
echo "========== [5/5] Verify outputs =========="
"$PY" - <<'PY' "$OUT_DIR"
import json, sys
from pathlib import Path
import pandas as pd

out = Path(sys.argv[1])
handoff = out / "agent_handoff_g_star_analysis.json"
summary = out / "g_star_analysis_summary.csv"
evidence = out / "g_star_kpi_evidence.csv"

h = json.loads(handoff.read_text())
gsa = h["g_star_analysis"]
print("pipeline:", h.get("pipeline"))
print("target_agent:", h.get("target_agent"))
print("analysis_rule:", gsa.get("analysis_rule"))
print("fdr_scope:", gsa.get("fdr_scope"))
print("fdr_n_hypotheses:", gsa.get("fdr_n_hypotheses"))
print("g_star_toolgroups:", gsa.get("g_star_toolgroups"))
assert "candidates" not in gsa

s = pd.read_csv(summary)
g_rows = s[s["in_g_star"] == 1]
ref = s[s["status"] == "not_in_g_star"]
ev = pd.read_csv(evidence)
print(f"\ng_star_analysis_summary: {len(s)} rows (G* tested={len(g_rows)}, not_in_g_star={len(ref)})")
print(f"  G* status breakdown:\n{g_rows['status'].value_counts().to_string()}")
print(f"\ng_star_kpi_evidence.csv rows: {len(ev)} (expected |G*|×5)")
print("\nDONE — artifacts in", out)
PY

echo ""
echo "All steps finished. Key files:"
echo "  $G_STAR_FILE"
echo "  $OUT_DIR/ml_alarm_audit_t*.csv"
echo "  $MANIFEST"
echo "  $OUT_DIR/agent_handoff_g_star_analysis.json"
echo "  $OUT_DIR/g_star_kpi_evidence.csv"
