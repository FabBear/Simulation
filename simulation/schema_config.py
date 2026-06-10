"""PostgreSQL schema SSOT for the simulation platform (default: simulation)."""
from __future__ import annotations

import os
from pathlib import Path


def _load_env_dotfiles() -> None:
    here = Path(__file__).resolve().parent
    for env_path in (here.parent / ".env", here.parent.parent / ".env"):
        if not env_path.is_file():
            continue
        try:
            for raw in env_path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip('"').strip("'")
                if key:
                    os.environ.setdefault(key, val)
        except OSError:
            continue


_load_env_dotfiles()

DB_SCHEMA = (os.getenv("POSTGRES_SCHEMA") or "simulation").strip() or "simulation"


def qualified_table(name: str) -> str:
    """Return schema-qualified table/view name for raw SQL."""
    if not DB_SCHEMA or DB_SCHEMA == "public":
        return name
    return f"{DB_SCHEMA}.{name}"
