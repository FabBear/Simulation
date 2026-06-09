#!/usr/bin/env python3
"""Load sim_csv_out CSV files into PostgreSQL with explicit column mapping."""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from csv_db_mapping import (  # noqa: E402
    CSV_TO_TABLE,
    DATA_CSV_FILES,
    KPI_FILE_TO_TABLE,
    LOAD_CSV_FILES,
    OPTIONAL_CSV_FILES,
    map_csv_row,
)
from database import SessionLocal, engine  # noqa: E402
from models import (  # noqa: E402
    KpiFab,
    KpiProcess,
    KpiTool,
    KpiToolgroup,
    KPI_LEVEL_MODELS,
    LotEventLog,
    LotReleaseLedger,
    SimulationLog,
    SimulationRun,
    ToolStateLog,
)

TABLE_MODEL = {
    "simulation_log": SimulationLog,
    "lot_event_log": LotEventLog,
    "tool_state_log": ToolStateLog,
    "lot_release_ledger": LotReleaseLedger,
    "kpi_fab": KpiFab,
    "kpi_process": KpiProcess,
    "kpi_toolgroup": KpiToolgroup,
    "kpi_tool": KpiTool,
}

BATCH_SIZE = 2000

_SCHEMA_SQL = (
    "V5__simulation_run_and_run_id.sql",
    "V6__kpi_level_tables.sql",
)


def _apply_schema_sql() -> None:
    for name in _SCHEMA_SQL:
        sql_path = _ROOT / "sql" / name
        if not sql_path.is_file():
            raise FileNotFoundError(f"Missing migration SQL: {sql_path}")
        with engine.begin() as conn:
            for stmt in sql_path.read_text(encoding="utf-8").split(";"):
                s = stmt.strip()
                if s:
                    conn.execute(text(s))


def _discover_run_id(csv_dir: Path, explicit: str | None) -> str:
    if explicit:
        return explicit.strip()
    for name in DATA_CSV_FILES:
        fp = csv_dir / name
        if not fp.is_file():
            continue
        with fp.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rid = (row.get("run_id") or "").strip()
                if rid:
                    return rid
    return csv_dir.name


def _read_csv_rows(csv_dir: Path, filename: str) -> list[dict[str, str]]:
    fp = csv_dir / filename
    if not fp.is_file():
        return []
    with fp.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _truncate_run(db, run_id: str) -> None:
    for model in (SimulationLog, LotEventLog, ToolStateLog, LotReleaseLedger, *KPI_LEVEL_MODELS):
        db.query(model).filter(model.run_id == run_id).delete(synchronize_session=False)
    db.query(SimulationRun).filter(SimulationRun.run_id == run_id).delete(synchronize_session=False)
    db.commit()


def _upsert_simulation_run(db, run_id: str, source_path: str, note: str | None) -> None:
    existing = db.query(SimulationRun).filter(SimulationRun.run_id == run_id).first()
    if existing:
        existing.source_path = source_path
        existing.imported_at = datetime.now(timezone.utc)
        existing.note = note
    else:
        db.add(
            SimulationRun(
                run_id=run_id,
                source_path=source_path,
                imported_at=datetime.now(timezone.utc),
                note=note,
            )
        )
    db.commit()


def load_directory(
    csv_dir: Path,
    run_id: str | None = None,
    *,
    dry_run: bool = False,
    truncate_run: bool = False,
    skip_schema: bool = False,
) -> dict[str, int]:
    csv_dir = csv_dir.resolve()
    if not csv_dir.is_dir():
        raise FileNotFoundError(f"Not a directory: {csv_dir}")

    present = [n for n in DATA_CSV_FILES if (csv_dir / n).is_file()]
    if not present:
        raise FileNotFoundError(
            f"No data CSV files in {csv_dir}. Expected any of: {', '.join(DATA_CSV_FILES)}"
        )

    rid = _discover_run_id(csv_dir, run_id)
    counts: dict[str, int] = {}

    if not skip_schema and not dry_run:
        _apply_schema_sql()

    if dry_run:
        for filename in LOAD_CSV_FILES:
            rows = _read_csv_rows(csv_dir, filename)
            if rows or filename not in OPTIONAL_CSV_FILES:
                counts[filename] = len(rows)
        print(f"[dry-run] run_id={rid} would load: {counts}")
        return counts

    db = SessionLocal()
    try:
        if truncate_run:
            _truncate_run(db, rid)
        _upsert_simulation_run(db, rid, str(csv_dir), note="load_csv_to_db.py")

        for filename in LOAD_CSV_FILES:
            fp = csv_dir / filename
            if not fp.is_file():
                if filename in OPTIONAL_CSV_FILES:
                    print(f"⚠️  skip missing optional: {filename}")
                    continue
                print(f"⚠️  skip missing: {filename}")
                continue

            rows = _read_csv_rows(csv_dir, filename)
            if not rows:
                counts[filename] = 0
                continue

            table = CSV_TO_TABLE[filename]
            model = TABLE_MODEL[table]
            mapped = [map_csv_row(filename, r, rid) for r in rows]

            for i in range(0, len(mapped), BATCH_SIZE):
                chunk = mapped[i : i + BATCH_SIZE]
                db.bulk_insert_mappings(model, chunk)
            db.commit()
            counts[filename] = len(mapped)
            print(f"✅ {filename} → {table}: {len(mapped)} rows")

        print(f"🎉 run_id={rid} import complete")
        return counts
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Load sim_csv_out CSVs into PostgreSQL")
    parser.add_argument("--csv-dir", type=Path, required=True, help="Directory with CSV outputs")
    parser.add_argument("--run-id", type=str, default=None, help="Episode run_id (default: from CSV)")
    parser.add_argument("--dry-run", action="store_true", help="Count rows only, no DB writes")
    parser.add_argument("--truncate-run", action="store_true", help="Delete existing rows for this run_id first")
    parser.add_argument("--skip-schema", action="store_true", help="Do not apply V5/V6 SQL (Flyway already applied)")
    args = parser.parse_args()

    try:
        load_directory(
            args.csv_dir,
            args.run_id,
            dry_run=args.dry_run,
            truncate_run=args.truncate_run,
            skip_schema=args.skip_schema,
        )
        return 0
    except Exception as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
