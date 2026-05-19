import json
from pathlib import Path

from core.snapshot_factory import SnapshotFactory
from schemas.snapshot_v2 import SnapshotV2


FIXTURES = Path(__file__).parent / "fixtures"


def test_snapshot_factory_builds_world():
    payload = json.loads((FIXTURES / "snapshot_v2_case1.json").read_text(encoding="utf-8"))
    snapshot = SnapshotV2.model_validate(payload)
    env, world = SnapshotFactory.create_env_from_snapshot(snapshot)

    assert float(env.now) == snapshot.sim_now_min
    assert "Litho_02" in world.machines
    assert world.machines["Litho_02"].queue[0].lot_id == "L_100"
    assert world.machines["Litho_03"].current_lot_id == "L_101"
