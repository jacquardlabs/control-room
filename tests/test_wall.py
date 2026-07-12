"""`compute_wall_summary`: the seven-state taxonomy collapsed to N/R/M, once.

Pinned to the design doc's wall bullet verbatim: N is grinding only, R is
review-ready only (never folded into N), M is input-blocked + question-
pending + parked + died, done inflates neither, and MASTER CAUTION
(`master_caution`) blinks for M only, never R.
"""

from __future__ import annotations

from datetime import UTC, datetime

from control_room.attention.models import AttentionEvent, AttentionSource, AttentionState
from control_room.wall import compute_wall_summary

_NOW = datetime(2026, 7, 12, tzinfo=UTC)


def _event(stream_id: str, state: AttentionState, *, reason: str | None = None) -> AttentionEvent:
    return AttentionEvent(
        stream_id=stream_id, state=state, reason=reason, source=AttentionSource.POLL, at=_NOW
    )


def test_empty_fleet_is_all_zero_and_no_caution():
    summary = compute_wall_summary([])
    assert summary.grinding == 0
    assert summary.review_ready == 0
    assert summary.need_you == 0
    assert summary.unacknowledged_need_you == 0
    assert summary.master_caution is False
    assert summary.aggregate_burn_usd is None


def test_review_ready_counts_separately_from_grinding():
    events = [
        _event("a", AttentionState.GRINDING),
        _event("b", AttentionState.GRINDING),
        _event("c", AttentionState.REVIEW_READY),
    ]
    summary = compute_wall_summary(events)
    assert summary.grinding == 2
    assert summary.review_ready == 1
    assert summary.need_you == 0
    assert summary.master_caution is False  # review-ready never claims the blink


def test_m_bucket_covers_input_blocked_question_pending_parked_and_died():
    events = [
        _event("a", AttentionState.INPUT_BLOCKED, reason="permission prompt"),
        _event("b", AttentionState.QUESTION_PENDING, reason="asked a question"),
        _event("c", AttentionState.PARKED, reason="judgment verdict"),
        _event("d", AttentionState.DIED),
    ]
    summary = compute_wall_summary(events)
    assert summary.need_you == 4
    assert summary.unacknowledged_need_you == 4
    assert summary.master_caution is True


def test_done_streams_inflate_no_count():
    events = [_event("a", AttentionState.DONE), _event("b", AttentionState.GRINDING)]
    summary = compute_wall_summary(events)
    assert summary.grinding == 1
    assert summary.review_ready == 0
    assert summary.need_you == 0


def test_unacknowledged_need_you_equals_need_you_until_ack_store_exists():
    """No ack mechanism exists yet (notifications-ack, issue #6) -- every
    M-bucket stream is unacknowledged by construction until then."""
    events = [_event("a", AttentionState.DIED), _event("b", AttentionState.PARKED, reason="r")]
    summary = compute_wall_summary(events)
    assert summary.unacknowledged_need_you == summary.need_you == 2


def test_aggregate_burn_defaults_to_none_not_a_fabricated_zero():
    summary = compute_wall_summary([_event("a", AttentionState.GRINDING)])
    assert summary.aggregate_burn_usd is None


def test_aggregate_burn_passthrough_when_supplied():
    summary = compute_wall_summary([], aggregate_burn_usd=4.20)
    assert summary.aggregate_burn_usd == 4.20
