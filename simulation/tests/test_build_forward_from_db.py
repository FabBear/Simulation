"""build_forward DB loaders vs CSV row loaders (no DB)."""
from __future__ import annotations

from tools.build_forward_scenario_from_csv import (
    _collect_arrival_rows,
    _load_kpi_tool_at_from_rows,
    _load_lot_traces_from_rows,
    _load_ltl_lock_from_rows,
    _load_release_ledger_from_rows,
    _load_tool_state_at_from_rows,
)


def test_kpi_tool_rows_match_csv_loader():
    t0 = 26820.0
    rows = [
        {"snapshot_time": "26820.0", "scope": "Etch_FE#1", "kpi_name": "q_len", "value": "3"},
        {"snapshot_time": "26820.0", "scope": "Etch_FE#1", "kpi_name": "processing_count", "value": "1"},
        {"snapshot_time": "26880.0", "scope": "Etch_FE#1", "kpi_name": "q_len", "value": "99"},
    ]
    q_len, proc = _load_kpi_tool_at_from_rows(rows, t0)
    assert q_len["Etch_FE#1"] == 3.0
    assert proc["Etch_FE#1"] == 1.0


def test_lot_traces_and_arrivals_from_row_dicts():
    t0 = 100.0
    t_end = 200.0
    lot_rows = [
        {
            "lot_id": "Lot_1",
            "product": "P3",
            "route_id": "Route_3",
            "event_type": "ARRIVAL",
            "event_time": "150.0",
            "step_seq": "",
            "detail_2": '{"due_date_sim_min": 5000}',
        },
        {
            "lot_id": "Lot_1",
            "product": "P3",
            "route_id": "Route_3",
            "event_type": "LOADING",
            "event_time": "160.0",
            "step_seq": "10",
            "tool_id": "Etch_FE#1",
            "detail_1": "5",
        },
    ]
    traces = _load_lot_traces_from_rows(lot_rows, t_end)
    assert "Lot_1" in traces
    assert traces["Lot_1"].arrival_time == 150.0
    arrivals = _collect_arrival_rows(lot_rows, t0, t_end)
    assert len(arrivals) == 1
    assert arrivals[0]["lot_id"] == "Lot_1"


def test_ledger_and_ltl_lock_from_rows():
    ledger_rows = [
        {
            "lot_id": "Lot_X",
            "sim_now_min": "120",
            "due_date_sim_min": "900",
            "product_name": "P",
            "route_name": "R",
            "is_super_hot": "0",
        }
    ]
    ledger = _load_release_ledger_from_rows(ledger_rows)
    assert ledger["Lot_X"]["product_name"] == "P"

    process_rows = [
        {"lot_id": "Lot_X", "step_seq": "5", "tool_id": "TG#1", "end_time": "100"},
        {"lot_id": "Lot_X", "step_seq": "6", "tool_id": "TG#2", "end_time": "150"},
    ]
    lock = _load_ltl_lock_from_rows(process_rows, t0=110.0)
    assert lock["Lot_X"][5] == "TG#1"
    assert 6 not in lock["Lot_X"]


def test_tool_state_at_from_rows():
    rows = [
        {"tool_id": "Etch_FE#1", "state": "IDLE", "state_change_time": "100", "lot_id": "", "setup_name": ""},
        {"tool_id": "Etch_FE#1", "state": "RUN", "state_change_time": "200", "lot_id": "Lot_1", "setup_name": "S1"},
    ]
    last, run_lot = _load_tool_state_at_from_rows(rows, t0=250.0)
    assert last["Etch_FE#1"]["state"] == "RUN"
    assert run_lot["Etch_FE#1"] == "Lot_1"
