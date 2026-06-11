#!/usr/bin/env python3
"""
Build a WHAT-IF scenario CSV bundle from a FORWARD baseline directory.

Copies T0 snapshots (tool, queue, wip) from baseline, applies release-plan diff,
and writes mes_whatif_action.csv + mes_scenario.meta.json.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_SNAPSHOT_COPY = (
    "mes_tool_snapshot.csv",
    "mes_tool_queue_snapshot.csv",
    "mes_wip_snapshot.csv",
)

_RELEASE_COLS = [
    "scenario_id", "product_name", "route_name", "release_time", "lots_count",
    "release_interval", "due_date_sim", "wafers_per_lot", "priority", "is_super_hot",
    "lot_type", "lot_name_prefix", "source_lot_release_id",
]

_WHATIF_COLS = [
    "seq", "action_kind", "effective_time", "lot_id", "route_id", "step_seq",
    "tool_group", "tool_id", "payload_json", "source",
]


def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fieldnames})


def _patch_releases(
    base_rows: list[dict],
    patch_rows: list[dict],
    scenario_id: str,
) -> list[dict]:
    """Merge plan patch by (product_name, route_name, release_time) key; else append."""
    if not patch_rows:
        out = []
        for r in base_rows:
            nr = dict(r)
            nr["scenario_id"] = scenario_id
            out.append(nr)
        return out

    def _key(r: dict) -> tuple:
        return (
            (r.get("product_name") or "").strip(),
            (r.get("route_name") or "").strip(),
            str(r.get("release_time") or "").strip(),
        )

    merged = {_key(r): dict(r) for r in base_rows}
    for pr in patch_rows:
        k = _key(pr)
        if k in merged:
            merged[k].update({k2: v for k2, v in pr.items() if v not in (None, "")})
        else:
            merged[k] = dict(pr)
    out = []
    for r in merged.values():
        r["scenario_id"] = scenario_id
        out.append(r)
    return out


def build_bundle(
    base_dir: Path,
    out_dir: Path,
    whatif_scenario_id: str,
    baseline_scenario_id: str,
    t0: float,
    horizon: float,
    plan_patch_csv: Path | None,
    whatif_actions_csv: Path | None,
    description: str,
) -> None:
    base_dir = base_dir.resolve()
    out_dir = out_dir.resolve()
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    for name in _SNAPSHOT_COPY:
        src = base_dir / name
        if not src.is_file():
            raise FileNotFoundError(f"Baseline missing {src}")
        shutil.copy2(src, out_dir / name)

    base_releases = _read_csv(base_dir / "mes_lot_release_plan.csv")
    patch_rows = _read_csv(plan_patch_csv) if plan_patch_csv else []
    release_rows = _patch_releases(base_releases, patch_rows, whatif_scenario_id)
    _write_csv(out_dir / "mes_lot_release_plan.csv", _RELEASE_COLS, release_rows)

    if whatif_actions_csv and whatif_actions_csv.is_file():
        shutil.copy2(whatif_actions_csv, out_dir / "mes_whatif_action.csv")
    elif (base_dir / "mes_whatif_action.csv").is_file():
        shutil.copy2(base_dir / "mes_whatif_action.csv", out_dir / "mes_whatif_action.csv")
    else:
        _write_csv(out_dir / "mes_whatif_action.csv", _WHATIF_COLS, [])

    meta = {
        "scenario_id": whatif_scenario_id,
        "mode": "WHATIF",
        "baseline_scenario_id": baseline_scenario_id,
        "t0_sim_minute": t0,
        "horizon_minutes": horizon,
        "use_master_lot_release": False,
        "description": description,
        "source_baseline_dir": str(base_dir),
    }
    (out_dir / "mes_scenario.meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    load_cmd = (
        f"python load_mes_scenario.py --create-tables "
        f"--scenario-id {whatif_scenario_id} --mode WHATIF --baseline {baseline_scenario_id} "
        f"--t0 {t0} --horizon {horizon} "
        f"--tools {out_dir / 'mes_tool_snapshot.csv'} "
        f"--queues {out_dir / 'mes_tool_queue_snapshot.csv'} "
        f"--wip {out_dir / 'mes_wip_snapshot.csv'} "
        f"--releases {out_dir / 'mes_lot_release_plan.csv'} "
        f"--whatif {out_dir / 'mes_whatif_action.csv'}"
    )
    (out_dir / "LOAD_COMMAND.txt").write_text(load_cmd + "\n", encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description="Build WHAT-IF scenario_out bundle from FORWARD baseline")
    p.add_argument("--base-dir", type=Path, required=True, help="scenario_out/FWD_BASE_* directory")
    p.add_argument("--out-dir", type=Path, default=None, help="Output dir (default scenario_out/<whatif-id>)")
    p.add_argument("--whatif-scenario-id", required=True)
    p.add_argument("--baseline-scenario-id", required=True)
    p.add_argument("--t0", type=float, required=True)
    p.add_argument("--horizon", type=float, default=120.0)
    p.add_argument("--plan-patch", type=Path, help="CSV rows to merge into mes_lot_release_plan")
    p.add_argument("--whatif-actions", type=Path, help="mes_whatif_action.csv source")
    p.add_argument("--description", default="WHAT-IF bundle from make_whatif_scenario_bundle.py")
    args = p.parse_args()

    out_dir = args.out_dir or (_ROOT / "scenario_out" / args.whatif_scenario_id)
    try:
        build_bundle(
            args.base_dir,
            out_dir,
            args.whatif_scenario_id,
            args.baseline_scenario_id,
            float(args.t0),
            float(args.horizon),
            args.plan_patch,
            args.whatif_actions,
            args.description,
        )
    except FileNotFoundError as exc:
        print(f"X {exc}", file=sys.stderr)
        return 1

    print(f"Wrote WHAT-IF bundle -> {out_dir}")
    print(f"  See {out_dir / 'LOAD_COMMAND.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
