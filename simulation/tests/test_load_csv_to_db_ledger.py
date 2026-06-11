"""lot_release_ledger.csv mapping tests."""
from __future__ import annotations

from csv_db_mapping import CSV_TO_TABLE, map_csv_row


def test_ledger_csv_table_mapping():
    assert CSV_TO_TABLE["lot_release_ledger.csv"] == "lot_release_ledger"


def test_map_ledger_row_bool_and_scenario():
    row = {
        "run_id": "run001",
        "scenario_id": "",
        "lot_id": "Lot_A",
        "lot_type": "Eng",
        "product_name": "Product_3",
        "route_name": "Route_3",
        "sim_now_min": "1000.0",
        "due_date_sim_min": "5000.0",
        "priority": "10",
        "is_super_hot": "1",
        "wafers_per_lot": "25",
        "source": "master",
    }
    out = map_csv_row("lot_release_ledger.csv", row, "run001")
    assert out["scenario_id"] is None
    assert out["is_super_hot"] is True
    assert out["lot_id"] == "Lot_A"
    assert out["sim_now_min"] == 1000.0
    assert out["wafers_per_lot"] == 25


def test_map_ledger_is_super_hot_false():
    row = {
        "run_id": "r",
        "scenario_id": "SC1",
        "lot_id": "L1",
        "lot_type": "",
        "product_name": "P",
        "route_name": "R",
        "sim_now_min": "1",
        "due_date_sim_min": "2",
        "priority": "0",
        "is_super_hot": "0",
        "wafers_per_lot": "1",
        "source": "",
    }
    out = map_csv_row("lot_release_ledger.csv", row, "r")
    assert out["is_super_hot"] is False
    assert out["scenario_id"] == "SC1"
