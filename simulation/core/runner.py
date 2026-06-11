from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from typing import Any

from core.action_injector import ActionInjector
from core.snapshot_factory import SnapshotFactory
from schemas.snapshot_v2 import LotStatus, SnapshotV2


@dataclass
class ScenarioResult:
    metrics: dict[str, float]
    metadata: dict[str, Any]


def _stable_hash(payload: dict) -> str:
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canon.encode("ascii")).hexdigest()


def run_scenario(
    snapshot: SnapshotV2,
    action: Any,
    seed: int,
    horizon_min: float,
) -> ScenarioResult:
    env, world = SnapshotFactory.create_env_from_snapshot(snapshot)
    rng = random.Random(seed)

    dispatch_rules = {machine_id: (lambda queue: queue) for machine_id in world.machines}
    if action is not None:
        injector = ActionInjector()
        injector.inject(world, action, now_sim_min=float(env.now), dispatch_rules=dispatch_rules)

    sim_horizon_min = float(horizon_min)
    env.run(until=float(env.now) + sim_horizon_min)

    waiting_lots = 0
    processing_lots = 0
    cqt_violations = 0
    queue_times = []
    for lot in world.lots.values():
        if lot.status == LotStatus.QUEUE:
            waiting_lots += 1
            queue_times.append(max(0.0, float(env.now) - lot.arrival_time_sim_min))
        elif lot.status == LotStatus.PROCESSING:
            processing_lots += 1
        if lot.cqt_deadline_sim_min is not None and float(env.now) > lot.cqt_deadline_sim_min:
            cqt_violations += 1

    avg_queue_time = (sum(queue_times) / len(queue_times)) if queue_times else 0.0
    metrics = {
        "avg_queue_time": round(avg_queue_time, 4),
        "cqt_scrap_count": float(cqt_violations),
        "waiting_lots": float(waiting_lots),
        "processing_lots": float(processing_lots),
        "random_probe": float(rng.random()),
    }
    snapshot_dict = snapshot.model_dump(mode="json")
    action_dict = action.model_dump(mode="json") if action is not None else {}
    metadata = {
        "seed": int(seed),
        "snapshot_hash": _stable_hash(snapshot_dict),
        "action_hash": _stable_hash(action_dict),
        "sim_horizon_min": sim_horizon_min,
    }
    return ScenarioResult(metrics=metrics, metadata=metadata)
