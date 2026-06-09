"""Unit tests for WHAT-IF DB clone helpers (no DB required)."""
from __future__ import annotations

import json
from pathlib import Path

from load_mes_scenario import _load_rows_from_path
from tools.make_whatif_scenario_bundle import _patch_releases


def test_patch_releases_merge_key():
    base = [
        {
            "scenario_id": "BASE",
            "product_name": "P3",
            "route_name": "R3",
            "release_time": 100.0,
            "lots_count": 1,
            "release_interval": 0,
            "due_date_sim": 5000.0,
            "wafers_per_lot": 25,
            "priority": 10,
            "is_super_hot": "false",
            "lot_type": "Lot_A",
            "lot_name_prefix": "",
            "source_lot_release_id": "",
        }
    ]
    patch = [
        {
            "product_name": "P3",
            "route_name": "R3",
            "release_time": 100.0,
            "priority": 99,
        }
    ]
    out = _patch_releases(base, patch, "WHATIF_1")
    assert len(out) == 1
    assert out[0]["scenario_id"] == "WHATIF_1"
    assert out[0]["priority"] == 99


def test_load_rows_from_json_actions(tmp_path: Path):
    fp = tmp_path / "actions.json"
    fp.write_text(
        json.dumps([{"action_kind": "LOT_HOLD", "effective_time": 26821.0, "lot_id": "L1"}]),
        encoding="utf-8",
    )
    rows = _load_rows_from_path(fp)
    assert len(rows) == 1
    assert rows[0]["action_kind"] == "LOT_HOLD"


def test_load_rows_from_csv_actions(tmp_path: Path):
    fp = tmp_path / "actions.csv"
    fp.write_text(
        "action_kind,effective_time,lot_id\nLOT_HOLD,26821,L1\n",
        encoding="utf-8",
    )
    rows = _load_rows_from_path(fp)
    assert len(rows) == 1
    assert rows[0]["effective_time"] == "26821"
