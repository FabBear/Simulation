"""Tests for lot_release_ledger.csv + DB logging at lot release."""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_HERE = Path(__file__).resolve().parent
_SIM = _HERE.parent
if str(_SIM) in sys.path:
    sys.path.remove(str(_SIM))
sys.path.insert(0, str(_SIM))
for _stale in ("fab_env", "models", "database"):
    sys.modules.pop(_stale, None)

os.environ.setdefault("SIM_END_MINUTES", "10")

import fab_env as _fab_env_mod  # noqa: E402

assert Path(_fab_env_mod.__file__).resolve().is_relative_to(_SIM)


def _make_env():
    return _fab_env_mod.FabEnv()


def test_log_lot_release_ledger_csv_absolute_due(tmp_path):
    env = _make_env()
    env._csv_run_id = "testrun001"
    env._sim_clock_offset = 1000.0
    env.sim_env = type("E", (), {"now": 50.0})()
    os.environ["SIM_CSV_DIR"] = str(tmp_path)

    env._log_lot_release_ledger(
        lot_id="Lot_A",
        lot_type="Engineering",
        product_name="Product_3",
        route_name="Route_Product_3",
        lot_due_date_rel=500.0,
        priority=10,
        is_super_hot=True,
        wafers_per_lot=25,
        source="mes_plan",
    )

    path = tmp_path / "lot_release_ledger.csv"
    assert path.is_file()
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["lot_id"] == "Lot_A"
    assert float(rows[0]["sim_now_min"]) == pytest.approx(1050.0)
    assert float(rows[0]["due_date_sim_min"]) == pytest.approx(1500.0)
    assert rows[0]["source"] == "mes_plan"
    assert int(rows[0]["is_super_hot"]) == 1
    assert env._kpi_release_ledger_count == 1


def test_source_process_writes_ledger(tmp_path):
    env = _make_env()
    env._csv_run_id = "runledger01"
    env.sim_env = _fab_env_mod.simpy.Environment()
    env.routes = {"Route_Product_3": []}
    os.environ["SIM_CSV_DIR"] = str(tmp_path)

    adapter = _fab_env_mod._LotReleaseLike(
        plan_id=1,
        product_name="Product_3",
        route_name="Route_Product_3",
        start_delay=0.0,
        lots_per_release=1,
        release_interval=0.0,
        wafers_per_lot=25,
        priority=5,
        due_date_minutes=1000.0,
        lot_type="LotType_X",
        is_super_hot_lot="no",
    )
    env.sim_env.process(env._source_process(adapter, release_source="mes_plan"))
    env.sim_env.run(until=0.1)

    path = tmp_path / "lot_release_ledger.csv"
    assert path.is_file()
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["product_name"] == "Product_3"
    assert rows[0]["source"] == "mes_plan"


def test_lot_process_arrival_detail2_is_none(monkeypatch):
    env = _make_env()
    env.sim_env = _fab_env_mod.simpy.Environment()
    env.routes = {
        "Route_Product_3": [
            SimpleNamespace(
                step_seq=1,
                target_tool_group="NoSuchTG",
                setup_id=None,
                step_name="S1",
                route_id="Route_Product_3",
                ltl_dedication_step=None,
            ),
        ],
    }
    env.machine_groups = {}

    captured = []

    def _capture_lot_event(*args, **kwargs):
        captured.append({"args": args, "kwargs": kwargs})

    monkeypatch.setattr(env, "_log_lot_event", _capture_lot_event)

    env.sim_env.process(
        env._lot_process("Lot_B", "Product_3", "Route_Product_3", 200.0, 0, 25, False)
    )
    env.sim_env.run(until=0.01)

    arrival = [c for c in captured if len(c["args"]) >= 7 and c["args"][6] == "ARRIVAL"]
    assert len(arrival) == 1
    assert arrival[0]["kwargs"].get("detail_2") is None
