"""`elevate_event`: bridging a board's own `parked` instrument onto the
stream's top-level `AttentionEvent` -- the fix for the generic detector's own
documented inability to ever produce `parked` itself.
"""

from __future__ import annotations

from datetime import UTC, datetime

from control_room.attention.models import AttentionEvent, AttentionSource, AttentionState
from control_room.board.elevate import elevate_event
from control_room.board.models import BoardSource, BoardView, Instrument

_NOW = datetime(2026, 7, 12, tzinfo=UTC)


_STREAM_ID = "workflow_run:epic-1"


def _event(state: AttentionState, *, reason: str | None = None) -> AttentionEvent:
    return AttentionEvent(
        stream_id=_STREAM_ID, state=state, reason=reason, source=AttentionSource.POLL, at=_NOW
    )


def _view(*instruments: Instrument) -> BoardView:
    return BoardView(stream_id=_STREAM_ID, source=BoardSource.PROTOCOL, instruments=instruments)


def _instrument(
    id: str, state: AttentionState, *, reason: str | None = None, label: str | None = None
) -> Instrument:
    return Instrument(id=id, label=label or id, state=state, reason=reason)


def test_grinding_stream_elevates_to_the_first_parked_instrument() -> None:
    event = _event(AttentionState.GRINDING)
    view = _view(
        _instrument("story-a", AttentionState.GRINDING),
        _instrument(
            "story-b", AttentionState.PARKED, reason="NEEDS DISCUSSION", label="auth-refresh"
        ),
    )
    elevated = elevate_event(event, view)
    assert elevated.state is AttentionState.PARKED
    assert elevated.reason == "auth-refresh: NEEDS DISCUSSION"
    assert elevated.source is AttentionSource.BOARD
    assert elevated.stream_id == event.stream_id


def test_review_ready_stream_also_elevates() -> None:
    """`review-ready` is the other placeholder state the generic detector can
    produce with no visibility into board-protocol parks -- also eligible."""
    event = _event(AttentionState.REVIEW_READY)
    view = _view(_instrument("story-a", AttentionState.PARKED, reason="r"))
    elevated = elevate_event(event, view)
    assert elevated.state is AttentionState.PARKED


def test_no_m_bucket_instrument_leaves_the_event_unchanged() -> None:
    event = _event(AttentionState.GRINDING)
    view = _view(
        _instrument("story-a", AttentionState.GRINDING),
        _instrument("story-b", AttentionState.DONE),
    )
    assert elevate_event(event, view) == event


def test_done_raw_state_is_never_elevated() -> None:
    """Terminal states are sticky (`control_room.shell.state`'s own
    invariant) -- a stream already `done` must never be resurrected as
    `parked` just because its last-read ledger snapshot hadn't caught up."""
    event = _event(AttentionState.DONE)
    view = _view(_instrument("story-a", AttentionState.PARKED, reason="r"))
    assert elevate_event(event, view) == event


def test_died_raw_state_is_never_overridden() -> None:
    """A liveness-confirmed `died` always wins over a stale board reading --
    matches `control_room.attention.detector.resolve_attention`'s own
    precedence."""
    event = _event(AttentionState.DIED)
    view = _view(_instrument("story-a", AttentionState.PARKED, reason="r"))
    assert elevate_event(event, view) == event


def test_a_live_hook_confirmed_amber_is_never_overridden_by_a_stale_board() -> None:
    """`input-blocked`/`question-pending` from a fresh hook signal is more
    specific and fresher than a ledger snapshot -- elevation only fills the
    gap where the generic detector has *nothing* amber to say, never
    competes with a real one."""
    event = _event(AttentionState.INPUT_BLOCKED, reason="permission prompt")
    view = _view(_instrument("story-a", AttentionState.PARKED, reason="r"))
    elevated = elevate_event(event, view)
    assert elevated.state is AttentionState.INPUT_BLOCKED
    assert elevated.reason == "permission prompt"


def test_picks_the_first_m_bucket_instrument_in_definition_order_not_worst() -> None:
    """ "Instruments never move" -- elevation walks `view.instruments`' own
    stable order, never a severity re-sort."""
    event = _event(AttentionState.GRINDING)
    view = _view(
        _instrument("story-a", AttentionState.PARKED, reason="first", label="story-a"),
        _instrument("story-b", AttentionState.PARKED, reason="second", label="story-b"),
    )
    elevated = elevate_event(event, view)
    assert elevated.reason == "story-a: first"


def test_instrument_with_no_reason_falls_back_to_its_label_alone() -> None:
    """Only reachable for a hypothetical M-bucket, non-amber instrument state
    (today, only `died` -- `Instrument`'s own amber-requires-reason validator
    forbids a reasonless `parked`) -- exercised directly here so
    `elevate_event`'s own fallback path isn't dead, untested code."""
    event = _event(AttentionState.GRINDING)
    view = _view(_instrument("story-a", AttentionState.DIED, label="story-a"))
    elevated = elevate_event(event, view)
    assert elevated.state is AttentionState.DIED
    assert elevated.reason == "story-a"
