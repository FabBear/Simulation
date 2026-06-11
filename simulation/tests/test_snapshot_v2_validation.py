import json
from pathlib import Path

import pytest

from schemas.snapshot_v2 import SnapshotV2


FIXTURES = Path(__file__).parent / "fixtures"


def test_snapshot_v2_valid():
    payload = json.loads((FIXTURES / "snapshot_v2_case1.json").read_text(encoding="utf-8"))
    snapshot = SnapshotV2.model_validate(payload)
    assert snapshot.snapshot_version == "2.0"
    assert snapshot.sim_now_min == 120.0


def test_snapshot_v2_invalid_location():
    payload = json.loads((FIXTURES / "snapshot_v2_case_invalid_location.json").read_text(encoding="utf-8"))
    with pytest.raises(Exception):
        SnapshotV2.model_validate(payload)
