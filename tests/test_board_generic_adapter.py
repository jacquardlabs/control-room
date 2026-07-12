"""Building a BoardView for a stream with no board protocol -- generic vitals only,
straight from stream-discovery/attention-detection's own output shapes."""

from __future__ import annotations

from datetime import UTC, datetime

from control_room.attention.models import AttentionEvent, AttentionSource, AttentionState
from control_room.board.generic_adapter import build_generic_board
from control_room.board.models import BoardSource
from control_room.models import StreamKind, StreamRecord

_NOW = datetime(2026, 7, 12, tzinfo=UTC)


def _stream(**overrides: object) -> StreamRecord:
    defaults = {
        "id": "interactive:abc",
        "kind": StreamKind.INTERACTIVE,
        "label": "my-session",
        "cwd": "/repo",
        "first_seen": _NOW,
        "last_seen": _NOW,
        "source_path": "/repo/.git/sessions/1.json",
    }
    defaults.update(overrides)
    return StreamRecord(**defaults)


def test_grinding_stream_has_no_cas_message() -> None:
    stream = _stream()
    event = AttentionEvent(
        stream_id=stream.id, state=AttentionState.GRINDING, source=AttentionSource.POLL, at=_NOW
    )
    view = build_generic_board(stream, event)
    assert view.source is BoardSource.GENERIC
    assert view.cas == ()
    assert view.instruments[0].state is AttentionState.GRINDING


def test_amber_stream_carries_its_reason_into_the_one_instrument() -> None:
    stream = _stream()
    event = AttentionEvent(
        stream_id=stream.id,
        state=AttentionState.QUESTION_PENDING,
        reason="asked which approach to take",
        source=AttentionSource.HOOK,
        at=_NOW,
    )
    view = build_generic_board(stream, event)
    instrument = view.instruments[0]
    assert instrument.state is AttentionState.QUESTION_PENDING
    assert instrument.reason == "asked which approach to take"
    assert len(view.cas) == 1
    assert "asked which approach to take" in view.cas[0].text


def test_generic_instrument_never_has_protocol_only_fields() -> None:
    stream = _stream()
    event = AttentionEvent(
        stream_id=stream.id,
        state=AttentionState.PARKED,
        reason="something",
        source=AttentionSource.POLL,
        at=_NOW,
    )
    view = build_generic_board(stream, event)
    instrument = view.instruments[0]
    assert instrument.fix_budget is None
    assert instrument.blocked_on == ()
    assert instrument.resolution_command is None


def test_died_stream_gets_a_cas_message_without_needing_a_reason() -> None:
    stream = _stream()
    event = AttentionEvent(
        stream_id=stream.id, state=AttentionState.DIED, source=AttentionSource.POLL, at=_NOW
    )
    view = build_generic_board(stream, event)
    assert len(view.cas) == 1
    assert view.instruments[0].reason is None


def test_instrument_id_and_label_come_from_the_stream() -> None:
    stream = _stream(id="job:xyz", label="background-cleanup")
    event = AttentionEvent(
        stream_id=stream.id, state=AttentionState.GRINDING, source=AttentionSource.POLL, at=_NOW
    )
    view = build_generic_board(stream, event)
    assert view.stream_id == "job:xyz"
    assert view.instruments[0].id == "job:xyz"
    assert view.instruments[0].label == "background-cleanup"
