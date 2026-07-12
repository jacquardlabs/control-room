"""Died detection: a mid-flight stream losing its process vs. a clean finish."""

from __future__ import annotations

import pytest

from control_room.attention.liveness import classify_liveness_transition
from control_room.attention.models import AttentionState
from control_room.models import LiveState


@pytest.mark.parametrize(
    "previous_state",
    [AttentionState.GRINDING, AttentionState.INPUT_BLOCKED, AttentionState.QUESTION_PENDING],
)
def test_grace_while_midflight_is_died(previous_state: AttentionState) -> None:
    assert classify_liveness_transition(previous_state, LiveState.GRACE) == AttentionState.DIED


@pytest.mark.parametrize(
    "previous_state", [AttentionState.REVIEW_READY, AttentionState.DONE, AttentionState.PARKED]
)
def test_grace_after_clean_finish_is_not_died(previous_state: AttentionState) -> None:
    """DESIGN.md's "instruments never move": a stream that already finished
    successfully is never retroactively relabeled died just because its
    process later exited (the terminal closing after the fact)."""
    assert classify_liveness_transition(previous_state, LiveState.GRACE) is None


def test_live_state_never_overrides_even_when_midflight() -> None:
    """A single missed poll (still LIVE per registry._grade) is a blip, not
    a grade change -- died is asserted only once discovery itself has
    decided the process is genuinely gone."""
    assert classify_liveness_transition(AttentionState.GRINDING, LiveState.LIVE) is None
