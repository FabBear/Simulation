import json
from pathlib import Path

from pydantic import TypeAdapter

from core.what_if_executor import run_what_if
from schemas.action_v1 import ActionV1
from schemas.snapshot_v2 import SnapshotV2


FIXTURES = Path(__file__).parent / "fixtures"


def test_parallel_matches_sequential():
    snapshot_payload = json.loads((FIXTURES / "snapshot_v2_case1.json").read_text(encoding="utf-8"))
    action_payload = json.loads((FIXTURES / "action_expedite.json").read_text(encoding="utf-8"))
    snapshot = SnapshotV2.model_validate(snapshot_payload)
    action = TypeAdapter(ActionV1).validate_python(action_payload)

    seq = run_what_if(snapshot, action, master_seed=42, horizon_min=720.0, mode="sequential")
    par = run_what_if(snapshot, action, master_seed=42, horizon_min=720.0, mode="parallel")

    assert seq.delta == par.delta
    assert seq.baseline_metrics == par.baseline_metrics
    assert seq.action_metrics == par.action_metrics
