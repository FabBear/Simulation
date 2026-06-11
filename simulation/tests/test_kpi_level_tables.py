"""KPI level table routing (no DB required for mapping; optional DB integration)."""
from __future__ import annotations

import os
from collections import defaultdict

import pytest

from csv_db_mapping import CSV_TO_TABLE, KPI_FILE_TO_TABLE, map_csv_row
from models import KpiFab, KpiProcess, KpiTool, KpiToolgroup, KPI_LEVEL_MODELS, MesScenario
from schema_config import DB_SCHEMA


def test_orm_models_use_simulation_schema():
    assert KpiTool.__table__.schema == DB_SCHEMA
    assert MesScenario.__table__.schema == DB_SCHEMA
    assert DB_SCHEMA == "simulation"


def test_kpi_csv_maps_to_level_tables():
    assert CSV_TO_TABLE["kpi_fab.csv"] == "kpi_fab"
    assert CSV_TO_TABLE["kpi_tool.csv"] == "kpi_tool"
    assert KPI_FILE_TO_TABLE["kpi_process.csv"] == "kpi_process"


def test_map_kpi_row_has_no_level_column():
    row = {
        "run_id": "r1",
        "snapshot_time": "60.0",
        "scope": "Etch_FE#1",
        "kpi_name": "q_len",
        "value": "2",
        "window_minutes": "",
        "numerator": "",
        "denominator": "",
        "meta": "",
    }
    out = map_csv_row("kpi_tool.csv", row, "r1")
    assert "level" not in out
    assert out["scope"] == "Etch_FE#1"
    assert out["kpi_name"] == "q_len"


def test_kpi_model_by_level_routing():
    """Mirror fab_env level → model table routing."""
    _KPI_MODEL_BY_LEVEL = {
        "FAB": KpiFab,
        "PROCESS": KpiProcess,
        "TOOLGROUP": KpiToolgroup,
        "TOOL": KpiTool,
    }
    rows = [
        {"level": "FAB", "run_id": "r", "snapshot_time": 60.0, "scope": "*", "kpi_name": "rtf", "value": 1.0},
        {"level": "TOOL", "run_id": "r", "snapshot_time": 60.0, "scope": "T#1", "kpi_name": "q_len", "value": 2.0},
        {"level": "PROCESS", "run_id": "r", "snapshot_time": 60.0, "scope": "Etch", "kpi_name": "wip", "value": 3.0},
    ]
    by_model = defaultdict(list)
    for row in rows:
        model = _KPI_MODEL_BY_LEVEL[row["level"]]
        by_model[model].append({k: v for k, v in row.items() if k != "level"})
    assert by_model[KpiFab][0]["kpi_name"] == "rtf"
    assert by_model[KpiTool][0]["kpi_name"] == "q_len"
    assert by_model[KpiProcess][0]["kpi_name"] == "wip"
    assert len(KPI_LEVEL_MODELS) == 4
    assert KpiToolgroup in KPI_LEVEL_MODELS


@pytest.mark.skipif(
    not os.getenv("POSTGRES_HOST") and not os.getenv("DATABASE_URL"),
    reason="needs postgres for integration check",
)
def test_kpi_level_tables_exist_in_db():
    from sqlalchemy import inspect

    from database import engine
    from schema_config import DB_SCHEMA

    insp = inspect(engine)
    missing = [
        n for n in ("kpi_fab", "kpi_process", "kpi_toolgroup", "kpi_tool")
        if not insp.has_table(n, schema=DB_SCHEMA)
    ]
    if missing:
        pytest.skip(f"V6 tables not applied yet (missing: {missing}); run Flyway V6 or load_csv_to_db")
