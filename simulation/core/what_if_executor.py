from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from enum import Enum

from core.runner import run_scenario
from schemas.snapshot_v2 import SnapshotV2


class ExecutionMode(str, Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"


@dataclass
class WhatIfResult:
    status: str
    baseline_metrics: dict
    action_metrics: dict
    delta: dict
    metadata: dict


def _run_serialized(snapshot_payload: dict, action_payload: dict | None, seed: int, horizon_min: float):
    from pydantic import TypeAdapter

    from schemas.action_v1 import ActionV1

    snapshot = SnapshotV2.model_validate(snapshot_payload)
    action = TypeAdapter(ActionV1).validate_python(action_payload) if action_payload else None
    return asdict(run_scenario(snapshot=snapshot, action=action, seed=seed, horizon_min=horizon_min))


def run_what_if(
    snapshot: SnapshotV2,
    action,
    master_seed: int,
    horizon_min: float,
    mode: str = ExecutionMode.SEQUENTIAL.value,
) -> WhatIfResult:
    mode = mode.lower()
    base_seed = int(master_seed)
    act_seed = int(master_seed)

    if mode == ExecutionMode.PARALLEL.value:
        snap = snapshot.model_dump(mode="json")
        action_payload = action.model_dump(mode="json") if action is not None else None
        with ProcessPoolExecutor(max_workers=2) as pool:
            fut_base = pool.submit(_run_serialized, snap, None, base_seed, horizon_min)
            fut_act = pool.submit(_run_serialized, snap, action_payload, act_seed, horizon_min)
            base = fut_base.result()
            act = fut_act.result()
    else:
        base = asdict(run_scenario(snapshot=snapshot, action=None, seed=base_seed, horizon_min=horizon_min))
        act = asdict(run_scenario(snapshot=snapshot, action=action, seed=act_seed, horizon_min=horizon_min))

    baseline_metrics = base["metrics"]
    action_metrics = act["metrics"]
    delta = {
        "saved_time_min": round(baseline_metrics["avg_queue_time"] - action_metrics["avg_queue_time"], 4),
        "saved_scraps": int(baseline_metrics["cqt_scrap_count"] - action_metrics["cqt_scrap_count"]),
    }
    metadata = {
        "mode": mode,
        "baseline": base["metadata"],
        "action": act["metadata"],
        "master_seed": int(master_seed),
    }
    return WhatIfResult(
        status="VALIDATED",
        baseline_metrics=baseline_metrics,
        action_metrics=action_metrics,
        delta=delta,
        metadata=metadata,
    )
