"""Unit tests for CSV → DB row mapping (no database required)."""

from csv_db_mapping import KPI_FILE_TO_LEVEL, map_csv_row


def test_map_simulation_process():
    row = {
        "run_id": "abc",
        "lot_id": "Lot_1",
        "product": "3",
        "route_id": "Route_3",
        "step_seq": "100",
        "step_name": "Etch",
        "tool_group": "Etch_FE",
        "tool_id": "Etch_FE#1",
        "arrive_time": "10.0",
        "start_time": "20.0",
        "end_time": "30.0",
        "queue_time": "10.0",
        "process_time": "10.0",
        "event_type": "PROCESS",
    }
    out = map_csv_row("simulation_process.csv", row, "abc")
    assert out["run_id"] == "abc"
    assert out["lot_id"] == "Lot_1"
    assert out["step_seq"] == 100
    assert out["tool_id"] == "Etch_FE#1"


def test_tool_id_empty_to_none():
    row = {
        "run_id": "x",
        "tool_group": "Litho_FE",
        "tool_id": "",
        "state": "IDLE",
        "state_change_time": "1.0",
        "setup_name": "",
        "lot_id": "",
        "reason": "INIT",
        "idle_units": "3",
        "run_units": "0",
        "setup_units": "0",
        "down_pm_units": "0",
        "down_bm_units": "0",
    }
    out = map_csv_row("tool_state.csv", row, "x")
    assert out["tool_id"] is None
    assert out["idle_units"] == 3


def test_kpi_level_from_filename():
    row = {
        "run_id": "r1",
        "snapshot_time": "60.0",
        "scope": "*",
        "kpi_name": "rtf",
        "value": "0.5",
        "window_minutes": "",
        "numerator": "1",
        "denominator": "2",
        "meta": "",
    }
    out = map_csv_row("kpi_fab.csv", row, "r1")
    assert out["level"] == "FAB"
    assert out["window_minutes"] is None
    assert out["kpi_name"] == "rtf"


def test_kpi_tool_level():
    assert KPI_FILE_TO_LEVEL["kpi_tool.csv"] == "TOOL"
