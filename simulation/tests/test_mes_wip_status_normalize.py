"""Unit tests for mes_wip_snapshot.status normalization on load."""
from __future__ import annotations

import pytest

from load_mes_scenario import normalize_mes_wip_status


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("QUEUING", "QUEUING"),
        ("queuing", "QUEUING"),
        ("QUEUE", "QUEUING"),
        ("PROCESSING", "PROCESSING"),
        ("TRANSPORT", "WAIT_TRANSPORT"),
        ("WAIT_TRANSPORT", "WAIT_TRANSPORT"),
        ("HOLD", "HOLD"),
        ("WAIT_BATCH", "WAIT_BATCH"),
    ],
)
def test_normalize_mes_wip_status_ok(raw: str, expected: str) -> None:
    assert normalize_mes_wip_status(raw) == expected


@pytest.mark.parametrize("raw", ["", "  ", "UNKNOWN", "RUNNING"])
def test_normalize_mes_wip_status_rejects(raw: str) -> None:
    with pytest.raises(ValueError, match="mes_wip_snapshot.status"):
        normalize_mes_wip_status(raw)
