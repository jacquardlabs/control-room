"""`build_fleet_payload`: the exact wire shape the static page consumes."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from control_room.attention.models import AttentionEvent, AttentionSource, AttentionState
from control_room.models import LiveState, StreamKind, StreamRecord
from control_room.shell.payload import build_fleet_payload
from control_room.shell.state import FleetSnapshot, StreamSnapshot
from control_room.wall import compute_wall_summary


def _stream(**overrides: object) -> StreamRecord:
    defaults = {
        "id": "interactive:abc",
        "kind": StreamKind.INTERACTIVE,
        "label": "my-session",
        "cwd": "/repo",
        "first_seen": datetime(2026, 7, 12, tzinfo=UTC),
        "last_seen": datetime(2026, 7, 12, tzinfo=UTC),
        "source_path": "/repo/sessions/1.json",
    }
    defaults.update(overrides)
    return StreamRecord(**defaults)


def test_payload_round_trips_through_json_with_expected_fields():
    stream = _stream()
    event = AttentionEvent(
        stream_id=stream.id,
        state=AttentionState.INPUT_BLOCKED,
        reason="permission prompt",
        source=AttentionSource.HOOK,
        at=stream.first_seen,
    )
    snapshot = FleetSnapshot(
        generated_at=stream.first_seen,
        wall=compute_wall_summary([event]),
        streams=(
            StreamSnapshot(
                stream=stream, event=event, board_html="<section>x</section>", acknowledged=False
            ),
        ),
    )

    payload = build_fleet_payload(snapshot, poll_interval_seconds=3.0)
    raw = json.loads(payload.model_dump_json())

    assert raw["poll_interval_seconds"] == 3.0
    assert raw["wall"]["need_you"] == 1
    assert raw["wall"]["master_caution"] is True
    (item,) = raw["streams"]
    assert item["id"] == "interactive:abc"
    assert item["attention_state"] == "input-blocked"
    assert item["reason"] == "permission prompt"
    assert item["live_state"] == LiveState.LIVE.value
    assert item["board_html"] == "<section>x</section>"
    assert item["bucket"] == "M"  # input-blocked -> M, via control_room.board.bucket.wall_bucket
    assert item["burn_usd"] is None  # StreamSnapshot's own default -- not fabricated
    assert item["acknowledged"] is False


def test_payload_passes_through_a_computed_burn_usd():
    stream = _stream()
    event = AttentionEvent(
        stream_id=stream.id,
        state=AttentionState.GRINDING,
        source=AttentionSource.POLL,
        at=stream.first_seen,
    )
    snapshot = FleetSnapshot(
        generated_at=stream.first_seen,
        wall=compute_wall_summary([event]),
        streams=(
            StreamSnapshot(
                stream=stream,
                event=event,
                board_html="<section/>",
                burn_usd=4.2,
                acknowledged=False,
            ),
        ),
    )

    payload = build_fleet_payload(snapshot, poll_interval_seconds=3.0)

    (item,) = payload.streams
    assert item.burn_usd == 4.2


def test_payload_bucket_is_none_for_done_and_grinding_is_n():
    """`build_fleet_payload` computes `bucket` itself (never re-derived
    client-side) -- `done` inflates no wall bucket, `grinding` is N."""
    done_stream = _stream(id="job:done-one")
    done_event = AttentionEvent(
        stream_id=done_stream.id,
        state=AttentionState.DONE,
        reason=None,
        source=AttentionSource.POLL,
        at=done_stream.first_seen,
    )
    grinding_stream = _stream(id="interactive:grinding-one")
    grinding_event = AttentionEvent(
        stream_id=grinding_stream.id,
        state=AttentionState.GRINDING,
        reason=None,
        source=AttentionSource.POLL,
        at=grinding_stream.first_seen,
    )
    snapshot = FleetSnapshot(
        generated_at=done_stream.first_seen,
        wall=compute_wall_summary([done_event, grinding_event]),
        streams=(
            StreamSnapshot(
                stream=done_stream, event=done_event, board_html="<section/>", acknowledged=False
            ),
            StreamSnapshot(
                stream=grinding_stream,
                event=grinding_event,
                board_html="<section/>",
                acknowledged=False,
            ),
        ),
    )

    payload = build_fleet_payload(snapshot, poll_interval_seconds=3.0)

    by_id = {item.id: item for item in payload.streams}
    assert by_id["job:done-one"].bucket is None
    assert by_id["interactive:grinding-one"].bucket == "N"


def test_payload_carries_acknowledged_through_from_the_snapshot():
    """`build_fleet_payload` reads `acknowledged` straight off `StreamSnapshot`
    -- it never re-derives it (`control_room.attention.ack.AckStore` is the
    one owner of that comparison, in `control_room.shell.state.FleetState`)."""
    stream = _stream()
    event = AttentionEvent(
        stream_id=stream.id,
        state=AttentionState.PARKED,
        reason="NEEDS DISCUSSION",
        source=AttentionSource.BOARD,
        at=stream.first_seen,
    )
    snapshot = FleetSnapshot(
        generated_at=stream.first_seen,
        wall=compute_wall_summary([event]),
        streams=(
            StreamSnapshot(stream=stream, event=event, board_html="<section/>", acknowledged=True),
        ),
    )

    payload = build_fleet_payload(snapshot, poll_interval_seconds=3.0)

    (item,) = payload.streams
    assert item.acknowledged is True


def test_empty_fleet_payload_has_empty_streams_tuple():
    snapshot = FleetSnapshot(
        generated_at=datetime.now(UTC),
        wall=compute_wall_summary([]),
        streams=(),
    )
    payload = build_fleet_payload(snapshot, poll_interval_seconds=3.0)
    assert payload.streams == ()
    assert payload.wall.grinding == 0
