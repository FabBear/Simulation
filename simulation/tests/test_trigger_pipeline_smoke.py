"""Smoke tests for L2 Trigger E2E pipeline entry points."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_SIM = Path(__file__).resolve().parents[1]
_FORWARD = _SIM / "tools" / "trigger_forward_pipeline.py"
_WHATIF = _SIM / "tools" / "trigger_whatif_pipeline.py"


def _parse_result_json(stdout: str) -> dict:
    start = stdout.rfind("\n{")
    if start == -1:
        start = stdout.find("{")
    else:
        start += 1
    assert start >= 0, f"no JSON in stdout:\n{stdout}"
    return json.loads(stdout[start:])


def test_forward_pipeline_db_source_dry_run(tmp_path: Path):
    g_star = tmp_path / "g_star.json"
    g_star.write_text(json.dumps({"toolgroups": ["TG1"]}), encoding="utf-8")
    out_dir = tmp_path / "forward_db_out"
    proc = subprocess.run(
        [
            sys.executable,
            str(_FORWARD),
            "--source",
            "db",
            "--run-id",
            "run_test",
            "--t0",
            "26820",
            "--horizon",
            "120",
            "--scenario-id",
            "FWD_BASE_T26820",
            "--g-star-file",
            str(g_star),
            "--n-runs",
            "5",
            "--out-dir",
            str(out_dir),
            "--dry-run",
        ],
        cwd=str(_SIM),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    combined = proc.stdout
    assert "build_forward_scenario_from_db.py" in combined
    assert "load_mes_scenario.py" not in combined
    assert combined.index("build_forward_scenario_from_db.py") < combined.index("run_monte_carlo_batch.py")


def test_forward_pipeline_dry_run_chain(tmp_path: Path):
    g_star = tmp_path / "g_star.json"
    g_star.write_text(json.dumps({"toolgroups": ["TG1"]}), encoding="utf-8")
    sim_dir = tmp_path / "sim_csv"
    sim_dir.mkdir()
    for name in ("lot_events.csv", "tool_state.csv", "kpi_tool.csv"):
        (sim_dir / name).write_text("run_id\n", encoding="utf-8")
    out_dir = tmp_path / "forward_out"
    proc = subprocess.run(
        [
            sys.executable,
            str(_FORWARD),
            "--sim-csv-dir",
            str(sim_dir),
            "--run-id",
            "run_test",
            "--t0",
            "26820",
            "--horizon",
            "120",
            "--scenario-id",
            "FWD_BASE_T26820",
            "--g-star-file",
            str(g_star),
            "--n-runs",
            "5",
            "--out-dir",
            str(out_dir),
            "--dry-run",
        ],
        cwd=str(_SIM),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    combined = proc.stdout
    i_build = combined.index("build_forward_scenario_from_csv.py")
    i_load = combined.index("load_mes_scenario.py")
    i_mc = combined.index("run_monte_carlo_batch.py")
    assert i_build < i_load < i_mc
    result = _parse_result_json(combined)
    assert result["track"] == "g_star_analysis"
    assert result["template_scenario_id"] == "FWD_BASE_T26820"
    assert "handoff_path" in result
    assert len(result["replica_scenario_ids"]) == 5


def test_whatif_pipeline_db_source_dry_run(tmp_path: Path):
    actions = tmp_path / "actions.csv"
    actions.write_text(
        "scenario_id,action_kind,effective_time\n"
        "FWD_WHATIF_T26820_RANK1,LOT_HOLD,26821\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "runs_manifest.csv"
    manifest.write_text(
        "run_index,seed,scenario_id,run_id,csv_dir,status\n"
        + "\n".join(f"{i},{i},FWD_BASE,run{i},/tmp/r{i},ok" for i in range(1, 6))
        + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "whatif_db_out"
    proc = subprocess.run(
        [
            sys.executable,
            str(_WHATIF),
            "--source",
            "db",
            "--baseline-scenario-id",
            "FWD_BASE_T26820",
            "--reuse-baseline-manifest",
            str(manifest),
            "--whatif-scenario-id",
            "FWD_WHATIF_T26820_RANK1",
            "--whatif-actions",
            str(actions),
            "--t0",
            "26820",
            "--horizon",
            "120",
            "--n-runs",
            "5",
            "--out-dir",
            str(out_dir),
            "--dry-run",
        ],
        cwd=str(_SIM),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    combined = proc.stdout
    assert "make_whatif_scenario_from_db.py" in combined
    assert "load_mes_scenario.py" not in combined
    i_make = combined.index("make_whatif_scenario_from_db.py")
    i_mc = combined.index("run_monte_carlo_batch.py")
    assert i_make < i_mc
    result = _parse_result_json(combined)
    assert result["track"] == "whatif"
    assert result["template_scenario_id"] == "FWD_WHATIF_T26820_RANK1"


def test_whatif_pipeline_dry_run_chain(tmp_path: Path):
    baseline_bundle = tmp_path / "baseline_bundle"
    baseline_bundle.mkdir()
    for name in (
        "mes_wip_snapshot.csv",
        "mes_tool_snapshot.csv",
        "mes_tool_queue_snapshot.csv",
        "mes_lot_release_plan.csv",
    ):
        (baseline_bundle / name).write_text("x\n1\n", encoding="utf-8")
    actions = tmp_path / "actions.csv"
    actions.write_text(
        "scenario_id,action_kind,effective_time\n"
        "FWD_WHATIF_T26820_RANK1,LOT_HOLD,26821\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "runs_manifest.csv"
    manifest.write_text(
        "run_index,seed,scenario_id,run_id,csv_dir,status\n"
        + "\n".join(f"{i},{i},FWD_BASE,run{i},/tmp/r{i},ok" for i in range(1, 6))
        + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "whatif_out"
    proc = subprocess.run(
        [
            sys.executable,
            str(_WHATIF),
            "--baseline-scenario-id",
            "FWD_BASE_T26820",
            "--baseline-bundle-dir",
            str(baseline_bundle),
            "--reuse-baseline-manifest",
            str(manifest),
            "--whatif-scenario-id",
            "FWD_WHATIF_T26820_RANK1",
            "--whatif-actions",
            str(actions),
            "--t0",
            "26820",
            "--horizon",
            "120",
            "--n-runs",
            "5",
            "--out-dir",
            str(out_dir),
            "--dry-run",
        ],
        cwd=str(_SIM),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    combined = proc.stdout
    i_make = combined.index("make_whatif_scenario_bundle.py")
    i_load = combined.index("load_mes_scenario.py")
    i_mc = combined.index("run_monte_carlo_batch.py")
    assert i_make < i_load < i_mc
    result = _parse_result_json(combined)
    assert result["track"] == "whatif"
    assert result["template_scenario_id"] == "FWD_WHATIF_T26820_RANK1"
    assert "handoff_path" in result


def test_whatif_fail_fast_missing_baseline_manifest(tmp_path: Path):
    baseline_bundle = tmp_path / "baseline_bundle"
    baseline_bundle.mkdir()
    actions = tmp_path / "actions.csv"
    actions.write_text("scenario_id,action_kind,effective_time\n", encoding="utf-8")
    out_dir = tmp_path / "whatif_out"
    proc = subprocess.run(
        [
            sys.executable,
            str(_WHATIF),
            "--baseline-scenario-id",
            "FWD_BASE_T26820",
            "--baseline-bundle-dir",
            str(baseline_bundle),
            "--reuse-baseline-manifest",
            str(tmp_path / "missing_manifest.csv"),
            "--whatif-scenario-id",
            "FWD_WHATIF_T26820_RANK1",
            "--whatif-actions",
            str(actions),
            "--t0",
            "26820",
            "--n-runs",
            "5",
            "--out-dir",
            str(out_dir),
        ],
        cwd=str(_SIM),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert not (out_dir / "agent_handoff_whatif.json").is_file()


def test_result_json_shape(tmp_path: Path):
    g_star = tmp_path / "g_star.json"
    g_star.write_text("{}", encoding="utf-8")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    for name in (
        "mes_wip_snapshot.csv",
        "mes_tool_snapshot.csv",
        "mes_tool_queue_snapshot.csv",
        "mes_lot_release_plan.csv",
    ):
        (bundle / name).write_text("h\n1\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    bundle_in_out = out_dir / "bundle"
    bundle_in_out.mkdir(parents=True)
    for name in (
        "mes_wip_snapshot.csv",
        "mes_tool_snapshot.csv",
        "mes_tool_queue_snapshot.csv",
        "mes_lot_release_plan.csv",
    ):
        (bundle_in_out / name).write_text("h\n1\n", encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(_FORWARD),
            "--t0",
            "26820",
            "--scenario-id",
            "FWD_BASE_T26820",
            "--g-star-file",
            str(g_star),
            "--n-runs",
            "5",
            "--out-dir",
            str(out_dir),
            "--skip-snapshot",
            "--skip-load",
            "--dry-run",
        ],
        cwd=str(_SIM),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    result = _parse_result_json(proc.stdout)
    assert result["handoff_path"].endswith("agent_handoff_g_star_analysis.json")
    assert result["template_scenario_id"] == "FWD_BASE_T26820"


def test_bundle_csv_paths_only_existing(tmp_path: Path):
    from tools._trigger_common import bundle_csv_paths

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "mes_wip_snapshot.csv").write_text("h\n", encoding="utf-8")
    (bundle / "mes_tool_snapshot.csv").write_text("h\n", encoding="utf-8")
    paths = bundle_csv_paths(bundle, existing_only=True)
    assert set(paths) == {"wip", "tools"}
