"""Paired manifest join tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_SIM = _HERE.parent
if str(_SIM) not in sys.path:
    sys.path.insert(0, str(_SIM))

from stats.common import RunMeta, build_paired_manifest_from_runs_manifest, write_runs_manifest


def test_seed_mismatch_raises(tmp_path: Path):
    m = tmp_path / "runs_manifest.csv"
    write_runs_manifest(m, [
        RunMeta(1, 10, tmp_path / "b1", "r1"),
    ])
    with pytest.raises(ValueError, match="seed mismatch"):
        build_paired_manifest_from_runs_manifest(
            m,
            [{"run_index": 1, "seed": 99, "csv_dir": str(tmp_path / "w1")}],
        )
