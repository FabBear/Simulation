"""Shared helpers for L2 Trigger E2E pipelines (forward / what-if)."""
from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_TOOLS = Path(__file__).resolve().parent

BUILD_FORWARD = _TOOLS / "build_forward_scenario_from_csv.py"
MAKE_WHATIF = _TOOLS / "make_whatif_scenario_bundle.py"
LOAD_MES = _ROOT / "load_mes_scenario.py"
RUN_MC = _TOOLS / "run_monte_carlo_batch.py"
_CLONE = _TOOLS / "clone_mes_scenarios_for_monte_carlo.py"

BUNDLE_CSV_MAP: dict[str, str] = {
    "wip": "mes_wip_snapshot.csv",
    "tools": "mes_tool_snapshot.csv",
    "queues": "mes_tool_queue_snapshot.csv",
    "releases": "mes_lot_release_plan.csv",
    "whatif": "mes_whatif_action.csv",
}

CORE_BUNDLE_KEYS = ("wip", "tools", "queues", "releases")


def bundle_csv_paths(bundle_dir: Path, *, existing_only: bool = True) -> dict[str, Path]:
    """Map bundle role -> CSV path (existing files only by default)."""
    out: dict[str, Path] = {}
    for key, name in BUNDLE_CSV_MAP.items():
        path = bundle_dir / name
        if path.is_file() or not existing_only:
            if path.is_file():
                out[key] = path
            elif not existing_only:
                out[key] = path
    return out


def expected_core_bundle_paths(bundle_dir: Path) -> dict[str, Path]:
    return {key: bundle_dir / BUNDLE_CSV_MAP[key] for key in CORE_BUNDLE_KEYS}


def csv_row_count(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open(encoding="utf-8", newline="") as f:
        return max(sum(1 for _ in f) - 1, 0)


def validate_bundle_not_empty(
    bundle_dir: Path,
    *,
    require_whatif: bool = False,
) -> None:
    paths = bundle_csv_paths(bundle_dir, existing_only=True)
    for key in CORE_BUNDLE_KEYS:
        if key not in paths:
            raise SystemExit(f"X missing bundle file: {bundle_dir / BUNDLE_CSV_MAP[key]}")
        if csv_row_count(paths[key]) == 0:
            raise SystemExit(f"X empty bundle CSV: {paths[key]}")
    if require_whatif:
        whatif_path = bundle_dir / BUNDLE_CSV_MAP["whatif"]
        if not whatif_path.is_file() or csv_row_count(whatif_path) == 0:
            raise SystemExit(f"X missing or empty whatif actions: {whatif_path}")


def run_step(cmd: list[str], *, dry_run: bool, cwd: Path | None = None) -> int:
    cwd = cwd or _ROOT
    print(" ".join(cmd))
    if dry_run:
        return 0
    proc = subprocess.run(cmd, cwd=str(cwd))
    return int(proc.returncode or 0)


def emit_result_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False))


def default_suffix_pattern(template_id: str) -> str:
    return f"{template_id}_R{{run:02d}}"


def _load_clone_mod():
    spec = importlib.util.spec_from_file_location("clone_mes_scenarios_for_monte_carlo", _CLONE)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def expand_replica_ids(template_id: str, suffix_pattern: str, n_runs: int) -> list[str]:
    clone_mod = _load_clone_mod()
    return clone_mod.expand_replica_scenario_ids(template_id, suffix_pattern, n_runs)


def build_load_mes_cmd(
    python: str,
    *,
    scenario_id: str,
    mode: str,
    t0: float,
    horizon: float,
    bundle_dir: Path,
    baseline: str = "",
    description: str = "",
    include_whatif: bool = False,
) -> list[str]:
    paths = expected_core_bundle_paths(bundle_dir)
    if include_whatif:
        paths["whatif"] = bundle_dir / BUNDLE_CSV_MAP["whatif"]
    cmd = [
        python,
        str(LOAD_MES),
        "--scenario-id",
        scenario_id,
        "--mode",
        mode,
        "--t0",
        str(t0),
        "--horizon",
        str(horizon),
    ]
    if baseline:
        cmd.extend(["--baseline", baseline])
    if description:
        cmd.extend(["--description", description])
    cmd.extend(["--wip", str(paths["wip"])])
    cmd.extend(["--tools", str(paths["tools"])])
    cmd.extend(["--queues", str(paths["queues"])])
    cmd.extend(["--releases", str(paths["releases"])])
    if include_whatif:
        cmd.extend(["--whatif", str(paths["whatif"])])
    return cmd


def count_ok_manifest_rows(manifest_path: Path) -> int:
    if not manifest_path.is_file():
        return 0
    ok = 0
    with manifest_path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("status") or "ok") == "ok":
                ok += 1
    return ok


def validate_baseline_manifest(manifest_path: Path, n_runs: int) -> None:
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_file():
        raise SystemExit(f"X baseline manifest not found: {manifest_path}")
    ok = count_ok_manifest_rows(manifest_path)
    if ok < n_runs:
        raise SystemExit(
            f"X baseline manifest {manifest_path} has {ok} ok rows, need {n_runs}"
        )


def validate_n_runs(n_runs: int) -> None:
    if n_runs < 5:
        raise SystemExit("X --n-runs must be >= 5")
