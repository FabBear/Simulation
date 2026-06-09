"""CSV column → DB table mapping (SSOT for load_csv_to_db.py)."""

from __future__ import annotations

from typing import Any, Callable, Optional

# CSV filename → KPI level (column not present in split CSV files; used for routing only)
KPI_FILE_TO_LEVEL: dict[str, str] = {
    "kpi_fab.csv": "FAB",
    "kpi_process.csv": "PROCESS",
    "kpi_toolgroup.csv": "TOOLGROUP",
    "kpi_tool.csv": "TOOL",
}

# CSV filename → SQLAlchemy table name (level-specific KPI tables)
KPI_FILE_TO_TABLE: dict[str, str] = {
    "kpi_fab.csv": "kpi_fab",
    "kpi_process.csv": "kpi_process",
    "kpi_toolgroup.csv": "kpi_toolgroup",
    "kpi_tool.csv": "kpi_tool",
}

# CSV filename → SQLAlchemy table name
CSV_TO_TABLE: dict[str, str] = {
    "simulation_process.csv": "simulation_log",
    "lot_events.csv": "lot_event_log",
    "tool_state.csv": "tool_state_log",
    "lot_release_ledger.csv": "lot_release_ledger",
    **KPI_FILE_TO_TABLE,
}

# Optional files (missing file → skip with warning)
OPTIONAL_CSV_FILES = frozenset({"simulation_process.csv", "lot_release_ledger.csv"})

# Expected for a full run (at least one must exist)
DATA_CSV_FILES = (
    "simulation_process.csv",
    "lot_events.csv",
    "tool_state.csv",
    *KPI_FILE_TO_LEVEL.keys(),
)

# All files attempted during load (optional files skipped when absent)
LOAD_CSV_FILES = DATA_CSV_FILES + ("lot_release_ledger.csv",)


def _empty_to_none(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, str) and val.strip() == "":
        return None
    return val


def _parse_float(val: Any) -> Optional[float]:
    val = _empty_to_none(val)
    if val is None:
        return None
    return float(val)


def _parse_int(val: Any) -> Optional[int]:
    val = _empty_to_none(val)
    if val is None:
        return None
    return int(float(val))


def _parse_str(val: Any) -> Optional[str]:
    return _empty_to_none(val) if val is None or isinstance(val, str) else str(val)


def _parse_bool(val: Any) -> bool:
    val = _empty_to_none(val)
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("1", "true", "yes", "y")


def _tool_id(val: Any) -> Optional[str]:
    """CSV aggregate rows use tool_id='' → DB NULL."""
    s = _parse_str(val)
    return None if s is None else s


# csv_column -> (db_column, converter)
SIMULATION_LOG_MAP: dict[str, tuple[str, Callable]] = {
    "lot_id": ("lot_id", _parse_str),
    "product": ("product", _parse_str),
    "route_id": ("route_id", _parse_str),
    "step_seq": ("step_seq", _parse_int),
    "step_name": ("step_name", _parse_str),
    "tool_group": ("tool_group", _parse_str),
    "tool_id": ("tool_id", _tool_id),
    "arrive_time": ("arrive_time", _parse_float),
    "start_time": ("start_time", _parse_float),
    "end_time": ("end_time", _parse_float),
    "queue_time": ("queue_time", _parse_float),
    "process_time": ("process_time", _parse_float),
    "event_type": ("event_type", _parse_str),
}

LOT_EVENT_LOG_MAP: dict[str, tuple[str, Callable]] = {
    "lot_id": ("lot_id", _parse_str),
    "product": ("product", _parse_str),
    "route_id": ("route_id", _parse_str),
    "step_seq": ("step_seq", _parse_int),
    "tool_group": ("tool_group", _parse_str),
    "tool_id": ("tool_id", _tool_id),
    "event_type": ("event_type", _parse_str),
    "event_time": ("event_time", _parse_float),
    "detail_1": ("detail_1", _parse_str),
    "detail_2": ("detail_2", _parse_str),
}

TOOL_STATE_LOG_MAP: dict[str, tuple[str, Callable]] = {
    "tool_group": ("tool_group", _parse_str),
    "tool_id": ("tool_id", _tool_id),
    "state": ("state", _parse_str),
    "state_change_time": ("state_change_time", _parse_float),
    "setup_name": ("setup_name", _parse_str),
    "lot_id": ("lot_id", _parse_str),
    "reason": ("reason", _parse_str),
    "idle_units": ("idle_units", _parse_int),
    "run_units": ("run_units", _parse_int),
    "setup_units": ("setup_units", _parse_int),
    "down_pm_units": ("down_pm_units", _parse_int),
    "down_bm_units": ("down_bm_units", _parse_int),
}

KPI_SNAPSHOT_MAP: dict[str, tuple[str, Callable]] = {
    "snapshot_time": ("snapshot_time", _parse_float),
    "scope": ("scope", _parse_str),
    "kpi_name": ("kpi_name", _parse_str),
    "value": ("value", _parse_float),
    "window_minutes": ("window_minutes", _parse_int),
    "numerator": ("numerator", _parse_float),
    "denominator": ("denominator", _parse_float),
    "meta": ("meta", _parse_str),
}

LOT_RELEASE_LEDGER_MAP: dict[str, tuple[str, Callable]] = {
    "scenario_id": ("scenario_id", _parse_str),
    "lot_id": ("lot_id", _parse_str),
    "lot_type": ("lot_type", _parse_str),
    "product_name": ("product_name", _parse_str),
    "route_name": ("route_name", _parse_str),
    "sim_now_min": ("sim_now_min", _parse_float),
    "due_date_sim_min": ("due_date_sim_min", _parse_float),
    "priority": ("priority", _parse_int),
    "is_super_hot": ("is_super_hot", _parse_bool),
    "wafers_per_lot": ("wafers_per_lot", _parse_int),
    "source": ("source", _parse_str),
}

CSV_COLUMN_MAP: dict[str, dict[str, tuple[str, Callable]]] = {
    "simulation_process.csv": SIMULATION_LOG_MAP,
    "lot_events.csv": LOT_EVENT_LOG_MAP,
    "tool_state.csv": TOOL_STATE_LOG_MAP,
    "lot_release_ledger.csv": LOT_RELEASE_LEDGER_MAP,
    **{k: KPI_SNAPSHOT_MAP for k in KPI_FILE_TO_LEVEL},
}


def map_csv_row(filename: str, row: dict[str, str], run_id: str) -> dict[str, Any]:
    """Map one CSV DictReader row to a DB insert dict (includes run_id)."""
    col_map = CSV_COLUMN_MAP[filename]
    out: dict[str, Any] = {"run_id": run_id}
    for csv_col, (db_col, conv) in col_map.items():
        out[db_col] = conv(row.get(csv_col))
    if filename == "lot_release_ledger.csv" and out.get("scenario_id") == "":
        out["scenario_id"] = None
    return out
