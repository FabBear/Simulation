#!/usr/bin/env python3
"""Runtime health-check for WHAT-IF P0/P1 (writes NDJSON to WHATIF_DEBUG_LOG_PATH)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

LOG_PATH = os.environ.get(
    "WHATIF_DEBUG_LOG_PATH",
    str(_ROOT.parents[1] / ".cursor" / "debug-c614ae.log"),
)


def _log(hypothesis_id: str, location: str, message: str, data: dict, run_id: str = "hc") -> None:
    # region agent log
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "sessionId": "c614ae",
                "runId": run_id,
                "hypothesisId": hypothesis_id,
                "location": location,
                "message": message,
                "data": data,
                "timestamp": int(datetime.now().timestamp() * 1000),
            }, ensure_ascii=True) + "\n")
    except Exception as exc:
        print(f"log write failed: {exc}", file=sys.stderr)
    # endregion


def _action(kind, payload, lot_id=None, **kw):
    class A:
        pass
    a = A()
    a.action_kind = kind
    a.payload_json = payload
    a.lot_id = lot_id
    a.tool_group = kw.get("tool_group")
    a.tool_id = kw.get("tool_id")
    a.id = kw.get("_id", 1)
    a.effective_time = 0.0
    a.step_seq = kw.get("step_seq")
    return a


def check_p0_actions() -> bool:
    import simpy
    import fab_env as fe

    env = fe.FabEnv()
    env.sim_env = simpy.Environment()
    env.active_lots_data["L1"] = {"lot_name": "L1", "status": "Queuing"}
    kinds = [
        ("LOT_PRIORITY", {"priority": 5}, "L1"),
        ("LOT_HOLD", {"reason": "t"}, "L1"),
        ("LOT_RELEASE", {}, "L1"),
        ("DISPATCH_RULE_OVERRIDE", {"tool_group": "TG", "dispatch_rule": "fifo"}, None),
        ("FORCE_TOOL", {"tool_id": "TG#1", "tool_group": "TG", "once": True}, "L1"),
        ("SKIP_RELEASE", {"mes_lot_release_plan_id": 9}, None),
    ]
    for kind, pl, lid in kinds:
        env._apply_whatif_action(_action(kind, pl, lid))
    unknown = env._mes_scenario_validation_report.get("unknown_actions", [])
    _log("H4", "healthcheck:p0_actions", "done", {"unknown_count": len(unknown), "unknown": unknown})
    return len(unknown) == 0


def check_requeue_integrity() -> bool:
    import simpy
    import fab_env as fe

    env = fe.FabEnv()
    env.sim_env = simpy.Environment()
    t1, t7 = "TG#1", "TG#7"
    for tid in (t1, t7):
        env.tools[tid] = {
            "group": "TG", "queue": [],
            "resource": simpy.Resource(env.sim_env, capacity=1),
            "current_setup": None, "toolgroup": None, "op_state": "IDLE",
        }
    env.machine_groups["TG"] = {"tool_ids": [t1, t7]}
    ev = env.sim_env.event()
    ev.payload = {"name": "Lot_A", "step_seq": 1, "req_setup": "S"}
    env.tools[t1]["queue"].append(ev)
    env.active_lots_data["Lot_A"] = {"status": "Queuing", "tool_id": t1}
    ok = env._requeue_lot_tool("Lot_A", "TG", t7, from_tool_id=t1)
    orphan_src = sum(1 for e in env.tools[t1]["queue"] if getattr(e, "payload", {}).get("name") == "Lot_A")
    dup_dst = sum(1 for e in env.tools[t7]["queue"] if getattr(e, "payload", {}).get("name") == "Lot_A")
    _log("H1", "healthcheck:requeue", "integrity", {
        "ok": ok, "orphan_src": orphan_src, "dst_count": dup_dst,
        "src_len": len(env.tools[t1]["queue"]), "dst_len": len(env.tools[t7]["queue"]),
    })
    return ok and orphan_src == 0 and dup_dst == 1


def check_requeue_empty_to_tool() -> bool:
    import fab_env as fe
    env = fe.FabEnv()
    env._mes_scenario_validation_report = {}
    ok = env._requeue_lot_tool("L", "TG", "")
    errs = env._mes_scenario_validation_report.get("action_errors", [])
    _log("H5", "healthcheck:requeue_empty_to", "reject_expected", {"ok": ok, "n_errors": len(errs)})
    return (not ok) and len(errs) >= 1


def check_compare_snapshot() -> bool:
    import csv
    from tools.compare_whatif import compare_dirs, _filter_snapshot, _read_kpi_rows

    with tempfile.TemporaryDirectory() as td:
        base = Path(td) / "b"
        wif = Path(td) / "w"
        base.mkdir()
        wif.mkdir()
        t0, h = 1000.0, 120.0
        target = t0 + h
        for d, val in ((base, 10.0), (wif, 15.0)):
            p = d / "kpi_fab.csv"
            with p.open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["run_id", "snapshot_time", "scope", "kpi_name", "value"])
                w.writeheader()
                w.writerow({"run_id": "r1", "snapshot_time": target + 0.5, "scope": "*", "kpi_name": "wip", "value": val})
        rows = _read_kpi_rows(base / "kpi_fab.csv")
        filt = _filter_snapshot(rows, target, tolerance=1.0)
        _log("H3", "healthcheck:compare_filter", "tolerance_hit", {
            "n_filtered": len(filt), "target": target,
        })
        summary, snap, _, _ = compare_dirs(base, wif, t0, h, tolerance=1.0)
        wip = next((r for r in summary if r["kpi_name"] == "wip"), None)
        _log("H3", "healthcheck:compare_delta", "wip", {
            "delta": wip.get("delta") if wip else None,
            "expected": 5.0,
        })
        return wip is not None and wip.get("delta") == 5.0


def check_pytest() -> bool:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q",
         "tests/test_whatif_set_super_hot.py",
         "tests/test_whatif_requeue_tool.py",
         "tests/test_compare_whatif.py",
         "tests/test_scenario_forward_smoke.py"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
    )
    _log("HC", "healthcheck:pytest", "exit", {
        "code": r.returncode,
        "tail": (r.stdout + r.stderr)[-500:],
    })
    return r.returncode == 0


def main() -> int:
    os.environ["WHATIF_DEBUG_LOG_PATH"] = LOG_PATH
    _log("HC", "healthcheck:main", "start", {"log_path": LOG_PATH})
    results = {
        "p0_actions": check_p0_actions(),
        "requeue_integrity": check_requeue_integrity(),
        "requeue_reject_empty": check_requeue_empty_to_tool(),
        "compare_kpi": check_compare_snapshot(),
        "pytest": check_pytest(),
    }
    all_ok = all(results.values())
    _log("HC", "healthcheck:main", "summary", {"results": results, "all_ok": all_ok})
    print(json.dumps(results, indent=2))
    print("ALL_OK" if all_ok else "FAILURES_PRESENT")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
