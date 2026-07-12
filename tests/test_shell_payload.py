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
        streams=(StreamSnapshot(stream=stream, event=event, board_html="<section>x</section>"),),
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


def test_empty_fleet_payload_has_empty_streams_tuple():
    snapshot = FleetSnapshot(
        generated_at=datetime.now(UTC),
        wall=compute_wall_summary([]),
        streams=(),
    )
    payload = build_fleet_payload(snapshot, poll_interval_seconds=3.0)
    assert payload.streams == ()
    assert payload.wall.grinding == 0
