"""Smoke tests for Monte Carlo scenario clone + batch guards."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_SIM = Path(__file__).resolve().parents[1]
_CLONE = _SIM / "tools" / "clone_mes_scenarios_for_monte_carlo.py"
_BATCH = _SIM / "tools" / "run_stat_batch.py"
_WRAPPER = _SIM / "tools" / "run_monte_carlo_batch.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_suffix_pattern_expansion():
    clone = _load_module(_CLONE, "clone_mc")
    ids = clone.expand_replica_scenario_ids(
        "FWD_WHATIF_T26820_STRONG",
        "{source}_R{run:02d}",
        3,
    )
    assert ids == [
        "FWD_WHATIF_T26820_STRONG_R01",
        "FWD_WHATIF_T26820_STRONG_R02",
        "FWD_WHATIF_T26820_STRONG_R03",
    ]


def test_format_replica_template_placeholder():
    clone = _load_module(_CLONE, "clone_mc2")
    rid = clone.format_replica_scenario_id(
        "FWD_BASE_T26820",
        "{template}_R{run:02d}",
        7,
    )
    assert rid == "FWD_BASE_T26820_R07"


def test_dry_run_lists_n_ids(capsys):
    proc = subprocess.run(
        [
            sys.executable,
            str(_CLONE),
            "--source-scenario-id",
            "FWD_BASE_T26820",
            "--suffix-pattern",
            "{source}_R{run:02d}",
            "--n-runs",
            "3",
            "--dry-run",
        ],
        cwd=str(_SIM),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "FWD_BASE_T26820_R01" in out
    assert "FWD_BASE_T26820_R03" in out


def test_run_stat_batch_single_id_forces_parallel_one(capsys):
    rsb = _load_module(_BATCH, "run_stat_batch")
    args = MagicMock(parallel=8)
    assert rsb._effective_parallel(args, ["FWD_BASE_T26820"]) == 1
    assert "forcing parallel=1" in capsys.readouterr().err
    assert rsb._effective_parallel(args, ["A", "B"]) == 8


def test_scenario_id_source_placeholder():
    rsb = _load_module(_BATCH, "run_stat_batch2")
    sid = rsb._scenario_id(
        "{source}_R{run:02d}",
        2,
        "FALLBACK",
        template="FWD_WHATIF_T26820_STRONG",
    )
    assert sid == "FWD_WHATIF_T26820_STRONG_R02"


def test_monte_carlo_block_includes_template():
    rsb = _load_module(_BATCH, "run_stat_batch3")
    args = MagicMock(
        n_runs=30,
        template_scenario_id="FWD_WHATIF_T26820_STRONG",
        whatif_suffix_pattern="FWD_WHATIF_T26820_STRONG_R{run:02d}",
        scenario_suffix_pattern="",
    )
    block = rsb._monte_carlo_block(
        args,
        effective_parallel=8,
        clone_manifest="clone_manifest.json",
    )
    assert block["n_runs"] == 30
    assert block["template_scenario_id"] == "FWD_WHATIF_T26820_STRONG"
    assert block["execution_mode"] == "parallel"


def test_clone_copies_whatif_actions_logic():
    clone = _load_module(_CLONE, "clone_mc3")
    db = MagicMock()
    source_row = MagicMock(
        scenario_id="SRC",
        action_kind="LOT_HOLD",
        seq=1,
        effective_time=100.0,
    )
    db.query.return_value.filter.return_value.all.return_value = [source_row]

    n = clone._copy_child_rows(db, clone.MesWhatifAction, "SRC", "SRC_R01")
    assert n == 1
    db.add.assert_called_once()
    added = db.add.call_args[0][0]
    assert added.scenario_id == "SRC_R01"
    assert added.action_kind == "LOT_HOLD"


def test_wrapper_dry_run_invokes_batch(tmp_path: Path):
    manifest = tmp_path / "runs_manifest.csv"
    manifest.write_text(
        "run_index,seed,scenario_id,run_id,csv_dir,status\n"
        + "\n".join(
            f"{i},{i},FWD_BASE,r{i},/tmp/r{i},ok" for i in range(1, 6)
        )
        + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "mc_out"
    proc = subprocess.run(
        [
            sys.executable,
            str(_WRAPPER),
            "--track",
            "whatif",
            "--template-scenario-id",
            "FWD_WHATIF_T26820_STRONG",
            "--skip-clone",
            "--reuse-baseline-manifest",
            str(manifest),
            "--baseline-scenario-id",
            "FWD_BASE_T26820",
            "--suffix-pattern",
            "FWD_WHATIF_T26820_STRONG_R{run:02d}",
            "--t0",
            "26820",
            "--n-runs",
            "5",
            "--out-dir",
            str(out_dir),
            "--dry-run",
        ],
        cwd=str(_SIM),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    combined = proc.stdout + proc.stderr
    assert "run_stat_batch.py" in combined
    assert "FWD_WHATIF_T26820_STRONG_R01" in combined
    assert "--whatif-suffix-pattern" in combined
