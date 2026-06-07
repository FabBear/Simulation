# Stat pipelines A (propagation) · B (what-if paired)

Operator guide for N=30 FabGuard PoC stats under `FAB_BEAR/simulation`.

## Locked decisions (summary)

| # | Topic |
|---|--------|
| 1–8 | N=30, H=120, REPORT bn SSOT, G* file, paired t, `--seed`, scenario R01…R30 |
| 9 | Optional merged `agent_handoff.json` |
| 10 | **A → save manifest → B**; B reuses baseline via `--reuse-baseline-manifest` |

## G* file format

```json
{ "toolgroups": ["Diffusion_FE_120", "Litho_FE_200"] }
```

Or CSV with header `toolgroup`.

Example: `simulation/sample_csv/g_star_T26820.json`

## Track A — 병목 확산 Agent

```bash
cd FAB_BEAR/simulation
.venv/bin/python tools/run_stat_batch.py \
  --mode propagation \
  --baseline-scenario-id FWD_BASE_T26820 \
  --scenario-suffix-pattern "FWD_BASE_T26820_R{run:02d}" \
  --t0 26820 --horizon 120 --n-runs 30 \
  --g-star-file sample_csv/g_star_T26820.json \
  --anchor-tg Diffusion_FE_120 \
  --out-dir out/stat_T26820 \
  --parallel 6
```

Outputs: `runs_manifest.csv`, `propagation_*.csv`, **`agent_handoff_propagation.json`**

Analysis only (no sim):

```bash
.venv/bin/python tools/stat_propagation_report.py \
  --runs-manifest out/stat_T26820/runs_manifest.csv \
  --g-star-file sample_csv/g_star_T26820.json \
  --t0 26820 --horizon 120 --n-runs 30 \
  --anchor-tg Diffusion_FE_120 \
  --out-dir out/stat_T26820 --level L2 --alpha 0.05
```

**Candidates (default L2):** `B ∉ G*`, not bottleneck @ T0, one-sided binomial  
`binomtest(k, N, p=max(p̂_null, 0.1)) < 0.05`. The 80% `emerge` rate is **reference tier only** (not evidence).  
`--level L1` = legacy demo (emerge-only, not statistical evidence).

## Track B — 대응안 검증 Agent

After what-if scenarios are `VALIDATED`:

```bash
.venv/bin/python tools/run_stat_batch.py \
  --mode whatif \
  --reuse-baseline-manifest out/stat_T26820/runs_manifest.csv \
  --whatif-scenario-id FWD_WHATIF_T26820_STRONG \
  --whatif-suffix-pattern "FWD_WHATIF_T26820_STRONG_R{run:02d}" \
  --t0 26820 --horizon 120 --n-runs 30 \
  --out-dir out/stat_T26820 \
  --parallel 6
```

Outputs: `paired_manifest.csv`, `whatif_paired_summary.csv`, **`agent_handoff_whatif.json`**

B does **not** re-run baseline sim when reusing manifest. B does **not** read `propagation_candidates`.

## Agent handoff files

| Agent | JSON | CSV |
|-------|------|-----|
| 병목 확산 | `agent_handoff_propagation.json` | `propagation_summary.csv`, `propagation_candidates.csv` |
| 대응안 검증 | `agent_handoff_whatif.json` | `whatif_paired_summary.csv` |

Optional merge: `--write-combined-handoff` → `agent_handoff.json`

## Review Q&A

1. **병목 SSOT:** `assign_bottleneck_labels` on TG wide @ T0+H (not t-test alone).
2. **후보 근거 (L2):** `binom_p < 0.05` with `p₀ = max(p̂_null, 0.1)`; `p̂_null = mean(k_g/N | g∉G*)`. **80% emerge is reference only.**
3. **t ≠ 확산:** paired t is for what-if effect only; propagation candidates use binomial L2.
4. **B baseline reuse:** Track B does not re-run baseline when `--reuse-baseline-manifest` is set.

## Tests

```bash
cd FAB_BEAR/simulation
.venv/bin/python -m pytest tests/test_stats_*.py tests/test_build_paired_manifest.py tests/test_run_sim_seed_arg.py -q
```
