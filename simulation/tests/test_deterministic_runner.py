import json
from pathlib import Path

from pydantic import TypeAdapter

from core.runner import run_scenario
from schemas.action_v1 import ActionV1
from schemas.snapshot_v2 import SnapshotV2


FIXTURES = Path(__file__).parent / "fixtures"


def test_deterministic_same_seed_same_result():
    snapshot_payload = json.loads((FIXTURES / "snapshot_v2_case1.json").read_text(encoding="utf-8"))
    action_payload = json.loads((FIXTURES / "action_expedite.json").read_text(encoding="utf-8"))
    snapshot = SnapshotV2.model_validate(snapshot_payload)
    action = TypeAdapter(ActionV1).validate_python(action_payload)

    r1 = run_scenario(snapshot=snapshot, action=action, seed=42, horizon_min=720.0)
    r2 = run_scenario(snapshot=snapshot, action=action, seed=42, horizon_min=720.0)

    assert r1.metrics == r2.metrics
    assert r1.metadata == r2.metadata
