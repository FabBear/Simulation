"""Unit tests for tools/compare_whatif.py (no Postgres)."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_TOOLS = _HERE.parent / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS.parent))

from tools.compare_whatif import compare_dirs, _write_summary  # noqa: E402


def _write_kpi(path: Path, run_id: str, snapshot_time: float, scope: str, kpi_name: str, value: float):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["run_id", "snapshot_time", "scope", "kpi_name", "value"],
        )
        w.writeheader()
        w.writerow({
            "run_id": run_id,
            "snapshot_time": snapshot_time,
            "scope": scope,
            "kpi_name": kpi_name,
            "value": value,
        })


def test_compare_dirs_delta(tmp_path: Path):
    base = tmp_path / "base"
    whatif = tmp_path / "whatif"
    t0, h = 10080.0, 120.0
    target = t0 + h
    _write_kpi(base / "kpi_fab.csv", "run_b", target, "*", "wip", 100.0)
    _write_kpi(whatif / "kpi_fab.csv", "run_w", target, "*", "wip", 110.0)
    _write_kpi(base / "kpi_toolgroup.csv", "run_b", target, "Litho_FE", "utilization_avg", 0.5)
    _write_kpi(whatif / "kpi_toolgroup.csv", "run_w", target, "Litho_FE", "utilization_avg", 0.6)

    summary, snap, b_run, w_run = compare_dirs(base, whatif, t0, h)
    assert snap == target
    assert b_run == "run_b"
    assert w_run == "run_w"
    by_key = {(r["level"], r["scope"], r["kpi_name"]): r for r in summary}
    assert by_key[("FAB", "*", "wip")]["delta"] == 10.0
    assert by_key[("TOOLGROUP", "Litho_FE", "utilization_avg")]["delta"] == pytest.approx(0.1)

    out = tmp_path / "summary.csv"
    _write_summary(out, summary, {
        "baseline_scenario_id": "B",
        "whatif_scenario_id": "W",
        "baseline_run_id": b_run,
        "whatif_run_id": w_run,
        "snapshot_time": snap,
    })
    assert out.is_file()
