"""run_sim_forward_once exposes --seed (no FabEnv run)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_RUNNER = Path(__file__).resolve().parents[1] / "run_sim_forward_once.py"


def test_help_lists_seed():
    proc = subprocess.run(
        [sys.executable, str(_RUNNER), "--help"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "--seed" in proc.stdout
