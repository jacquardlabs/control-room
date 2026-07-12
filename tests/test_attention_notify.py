"""`evaluate`: the one notify decision, plus the debounce/hysteresis and
ack-interaction rules issue #6's acceptance criteria name directly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from control_room.attention.ack import AckRecord
from control_room.attention.models import AttentionEvent, AttentionSource, AttentionState
from control_room.attention.notify import NOTIFY_HYSTERESIS, evaluate
from control_room.board.bucket import WallBucket

_NOW = datetime(2026, 7, 12, 12, 0, 0, tzinfo=UTC)


def _event(state: AttentionState, reason: str | None = None, at: datetime = _NOW) -> AttentionEvent:
    return AttentionEvent(
        stream_id="s1", state=state, reason=reason, source=AttentionSource.POLL, at=at
    )


def test_non_m_bucket_never_fires_and_resets_the_record() -> None:
    record = AckRecord(
        acknowledged_state=AttentionState.PARKED,
        acknowledged_reason="r",
        last_notified_state=AttentionState.PARKED,
        last_notified_reason="r",
        last_notified_at=_NOW,
    )
    decision = evaluate(_event(AttentionState.GRINDING), WallBucket.N, record, now=_NOW)
    assert decision.should_fire is False
    assert decision.record == AckRecord()


def test_fresh_m_bucket_event_fires_and_records_it() -> None:
    decision = evaluate(
        _event(AttentionState.PARKED, "NEEDS DISCUSSION"), WallBucket.M, AckRecord(), now=_NOW
    )
    assert decision.should_fire is True
    assert decision.record.last_notified_state is AttentionState.PARKED
    assert decision.record.last_notified_reason == "NEEDS DISCUSSION"
    assert decision.record.last_notified_at == _NOW


def test_acknowledged_identity_never_fires() -> None:
    record = AckRecord(acknowledged_state=AttentionState.PARKED, acknowledged_reason="r")
    decision = evaluate(_event(AttentionState.PARKED, "r"), WallBucket.M, record, now=_NOW)
    assert decision.should_fire is False
    assert decision.record == record  # unchanged -- nothing to update


def test_same_identity_as_last_notified_never_fires_again() -> None:
    """Issue #6, verbatim: never notifies twice for the same unacked state."""
    record = AckRecord(
        last_notified_state=AttentionState.PARKED, last_notified_reason="r", last_notified_at=_NOW
    )
    later = _NOW + timedelta(hours=1)  # long past any debounce window
    decision = evaluate(
        _event(AttentionState.PARKED, "r", at=later), WallBucket.M, record, now=later
    )
    assert decision.should_fire is False
    assert decision.record == record


def test_a_different_identity_within_the_hysteresis_window_is_suppressed() -> None:
    """The debounce: a detector flickering near a classification boundary
    (design doc's own example) must not burst notifications."""
    record = AckRecord(
        last_notified_state=AttentionState.INPUT_BLOCKED,
        last_notified_reason="permission prompt",
        last_notified_at=_NOW,
    )
    moment_later = _NOW + (NOTIFY_HYSTERESIS / 2)
    decision = evaluate(
        _event(AttentionState.QUESTION_PENDING, "different reason", at=moment_later),
        WallBucket.M,
        record,
        now=moment_later,
    )
    assert decision.should_fire is False
    assert decision.record == record


def test_a_different_identity_past_the_hysteresis_window_fires_again() -> None:
    record = AckRecord(
        last_notified_state=AttentionState.INPUT_BLOCKED,
        last_notified_reason="permission prompt",
        last_notified_at=_NOW,
    )
    well_later = _NOW + NOTIFY_HYSTERESIS + timedelta(seconds=1)
    decision = evaluate(
        _event(AttentionState.PARKED, "a genuinely separate problem", at=well_later),
        WallBucket.M,
        record,
        now=well_later,
    )
    assert decision.should_fire is True
    assert decision.record.last_notified_state is AttentionState.PARKED
    assert decision.record.last_notified_reason == "a genuinely separate problem"


def test_hysteresis_boundary_is_exclusive() -> None:
    """Exactly `NOTIFY_HYSTERESIS` later still counts as within the window --
    only strictly *more* than the window has elapsed re-arms notification."""
    record = AckRecord(
        last_notified_state=AttentionState.INPUT_BLOCKED,
        last_notified_reason="r1",
        last_notified_at=_NOW,
    )
    exactly_at_boundary = _NOW + NOTIFY_HYSTERESIS
    decision = evaluate(
        _event(AttentionState.PARKED, "r2", at=exactly_at_boundary),
        WallBucket.M,
        record,
        now=exactly_at_boundary,
    )
    assert decision.should_fire is False


def test_acknowledging_one_identity_does_not_suppress_a_later_different_one() -> None:
    """Acknowledge resets the *acknowledged* identity only for that specific
    state+reason -- a subsequent, different identity is still new and fires,
    matching "resets correctly on a new event" (issue #6)."""
    record = AckRecord(acknowledged_state=AttentionState.PARKED, acknowledged_reason="r1")
    decision = evaluate(
        _event(AttentionState.QUESTION_PENDING, "r2"), WallBucket.M, record, now=_NOW
    )
    assert decision.should_fire is True
