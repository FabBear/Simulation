import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from schemas.action_v1 import ActionV1


FIXTURES = Path(__file__).parent / "fixtures"


def test_action_valid():
    payload = json.loads((FIXTURES / "action_expedite.json").read_text(encoding="utf-8"))
    action = TypeAdapter(ActionV1).validate_python(payload)
    assert action.action_type == "EXPEDITE"


def test_action_ratio_invalid():
    payload = json.loads((FIXTURES / "action_expedite.json").read_text(encoding="utf-8"))
    payload["parameters"]["ratio"] = 1.5
    with pytest.raises(Exception):
        TypeAdapter(ActionV1).validate_python(payload)
