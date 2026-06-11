"""Smoke: run_stat_batch promote + dry-run wiring."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_SIM = Path(__file__).resolve().parents[1]
_BATCH_PATH = _SIM / "tools" / "run_stat_batch.py"


def _load_batch():
    spec = importlib.util.spec_from_file_location("run_stat_batch", _BATCH_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_scenario_ids_for_batch_unique_suffix():
    rsb = _load_batch()
    ids = rsb._scenario_ids_for_batch(
        "FWD_WHATIF_R{run:02d}",
        "FWD_WHATIF",
        range(1, 4),
    )
    assert ids == ["FWD_WHATIF_R01", "FWD_WHATIF_R02", "FWD_WHATIF_R03"]


def test_scenario_ids_for_batch_single_id():
    rsb = _load_batch()
    ids = rsb._scenario_ids_for_batch("", "FWD_BASE_T26820", range(1, 31))
    assert ids == ["FWD_BASE_T26820"]


def test_skip_promote_skips_promote_calls(monkeypatch):
    rsb = _load_batch()
    calls: list[str] = []

    def track(_python, scenario_id, *, dry_run):
        calls.append(scenario_id)
        return 0

    monkeypatch.setattr(rsb, "_promote_scenario", track)

    class Args:
        skip_promote = True
        dry_run = False
        python = sys.executable

    rsb._promote_before_batch(Args(), ["FWD_BASE_T26820"])
    assert calls == []

    Args.skip_promote = False
    rsb._promote_before_batch(Args(), ["FWD_BASE_T26820"])
    assert calls == ["FWD_BASE_T26820"]


def test_dry_run_prints_promote(tmp_path: Path):
    g_star = tmp_path / "g_star.json"
    g_star.write_text(json.dumps({"toolgroups": ["TG1"]}), encoding="utf-8")
    out_dir = tmp_path / "out"
    proc = subprocess.run(
        [
            sys.executable,
            str(_BATCH_PATH),
            "--mode",
            "g_star_analysis",
            "--dry-run",
            "--g-star-file",
            str(g_star),
            "--baseline-scenario-id",
            "FWD_BASE_T26820",
            "--baseline-csv-dir",
            str(tmp_path),
            "--t0",
            "26820",
            "--n-runs",
            "5",
            "--out-dir",
            str(out_dir),
        ],
        cwd=str(_SIM),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    combined = proc.stdout + proc.stderr
    assert "promote_scenario_validated.py" in combined
    assert "FWD_BASE_T26820" in combined


def test_dry_run_whatif_suffix_promotes_all(tmp_path: Path):
    manifest = tmp_path / "runs_manifest.csv"
    manifest.write_text(
        "run_index,seed,scenario_id,run_id,csv_dir,status\n"
        "1,1,FWD_BASE,run1,/tmp/r1,ok\n"
        "2,2,FWD_BASE,run2,/tmp/r2,ok\n"
        "3,3,FWD_BASE,run3,/tmp/r3,ok\n"
        "4,4,FWD_BASE,run4,/tmp/r4,ok\n"
        "5,5,FWD_BASE,run5,/tmp/r5,ok\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "whatif_out"
    proc = subprocess.run(
        [
            sys.executable,
            str(_BATCH_PATH),
            "--mode",
            "whatif",
            "--dry-run",
            "--reuse-baseline-manifest",
            str(manifest),
            "--baseline-scenario-id",
            "FWD_BASE_T26820",
            "--whatif-scenario-id",
            "FWD_WHATIF",
            "--whatif-suffix-pattern",
            "FWD_WHATIF_R{run:02d}",
            "--t0",
            "26820",
            "--n-runs",
            "5",
            "--out-dir",
            str(out_dir),
        ],
        cwd=str(_SIM),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    combined = proc.stdout + proc.stderr
    for i in range(1, 6):
        assert f"FWD_WHATIF_R{i:02d}" in combined


def test_fail_fast_on_failed_baseline_runs(monkeypatch, tmp_path: Path):
    rsb = _load_batch()
    g_star = tmp_path / "g.json"
    g_star.write_text(json.dumps({"toolgroups": ["TG1"]}), encoding="utf-8")

    def fake_batch(args, out_dir, *, skip_if_exists):
        return [
            rsb.RunMeta(1, 1, out_dir / "r1", "", "FWD_BASE", "failed"),
        ]

    monkeypatch.setattr(rsb, "_run_baseline_batch", fake_batch)

    argv = [
        "run_stat_batch.py",
        "--mode",
        "g_star_analysis",
        "--g-star-file",
        str(g_star),
        "--baseline-scenario-id",
        "FWD_BASE",
        "--baseline-csv-dir",
        str(tmp_path),
        "--t0",
        "26820",
        "--n-runs",
        "5",
        "--out-dir",
        str(tmp_path / "out"),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    assert rsb.main() == 1
    assert not (tmp_path / "out" / "agent_handoff_g_star_analysis.json").is_file()
