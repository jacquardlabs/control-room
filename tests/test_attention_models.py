"""AttentionEvent's amber-requires-reason invariant (DESIGN.md, verbatim)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from control_room.attention.models import AttentionEvent, AttentionSource, AttentionState

NOW = datetime(2026, 7, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    "state", [AttentionState.INPUT_BLOCKED, AttentionState.QUESTION_PENDING, AttentionState.PARKED]
)
def test_amber_state_without_reason_is_rejected(state: AttentionState) -> None:
    with pytest.raises(ValidationError, match="requires a one-clause reason"):
        AttentionEvent(
            stream_id="interactive:abc", state=state, source=AttentionSource.HOOK, at=NOW
        )


@pytest.mark.parametrize(
    "state", [AttentionState.INPUT_BLOCKED, AttentionState.QUESTION_PENDING, AttentionState.PARKED]
)
def test_amber_state_with_whitespace_only_reason_is_rejected(state: AttentionState) -> None:
    with pytest.raises(ValidationError, match="requires a one-clause reason"):
        AttentionEvent(
            stream_id="interactive:abc",
            state=state,
            reason="   ",
            source=AttentionSource.HOOK,
            at=NOW,
        )


@pytest.mark.parametrize(
    "state", [AttentionState.INPUT_BLOCKED, AttentionState.QUESTION_PENDING, AttentionState.PARKED]
)
def test_amber_state_with_reason_is_accepted(state: AttentionState) -> None:
    event = AttentionEvent(
        stream_id="interactive:abc",
        state=state,
        reason="auth-refresh parked",
        source=AttentionSource.HOOK,
        at=NOW,
    )
    assert event.reason == "auth-refresh parked"


@pytest.mark.parametrize(
    "state",
    [
        AttentionState.GRINDING,
        AttentionState.REVIEW_READY,
        AttentionState.DIED,
        AttentionState.DONE,
    ],
)
def test_non_amber_states_do_not_require_a_reason(state: AttentionState) -> None:
    event = AttentionEvent(
        stream_id="interactive:abc", state=state, source=AttentionSource.POLL, at=NOW
    )
    assert event.reason is None


def test_state_values_match_design_md_vocabulary_verbatim() -> None:
    """DESIGN.md: "one name per concept across UI, schema keys, notifications, and docs." """
    assert {s.value for s in AttentionState} == {
        "grinding",
        "input-blocked",
        "question-pending",
        "parked",
        "review-ready",
        "died",
        "done",
    }
