"""The one wall-bucket mapping function -- exhaustive over all seven states."""

from __future__ import annotations

import pytest

from control_room.attention.models import AttentionState
from control_room.board.bucket import WallBucket, wall_bucket


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (AttentionState.GRINDING, WallBucket.N),
        (AttentionState.REVIEW_READY, WallBucket.R),
        (AttentionState.INPUT_BLOCKED, WallBucket.M),
        (AttentionState.QUESTION_PENDING, WallBucket.M),
        (AttentionState.PARKED, WallBucket.M),
        (AttentionState.DIED, WallBucket.M),
        (AttentionState.DONE, None),
    ],
)
def test_wall_bucket_covers_every_state(state: AttentionState, expected: WallBucket | None) -> None:
    assert wall_bucket(state) is expected


def test_every_attention_state_is_classified() -> None:
    """No state silently falls through to an unhandled default -- every one
    of the seven states has an explicit, tested bucket (or None) above."""
    tested_states = {
        AttentionState.GRINDING,
        AttentionState.REVIEW_READY,
        AttentionState.INPUT_BLOCKED,
        AttentionState.QUESTION_PENDING,
        AttentionState.PARKED,
        AttentionState.DIED,
        AttentionState.DONE,
    }
    assert tested_states == set(AttentionState)
