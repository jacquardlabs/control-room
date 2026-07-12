from __future__ import annotations

from datetime import UTC, datetime

from control_room.models import LiveState, StreamKind, StreamRecord


def test_stream_record_round_trips_through_json():
    now = datetime.now(UTC)
    record = StreamRecord(
        id="interactive:abc",
        kind=StreamKind.INTERACTIVE,
        label="abc",
        cwd="/tmp/x",
        pid=123,
        first_seen=now,
        last_seen=now,
        source_path="/tmp/sessions/123.json",
    )

    restored = StreamRecord.model_validate_json(record.model_dump_json())

    assert restored == record
    assert restored.live_state == LiveState.LIVE
    assert restored.consecutive_misses == 0


def test_stream_kind_and_live_state_serialize_as_plain_strings():
    now = datetime.now(UTC)
    record = StreamRecord(
        id="job:x",
        kind=StreamKind.BACKGROUND_TASK,
        label="x",
        cwd="/tmp",
        first_seen=now,
        last_seen=now,
        source_path="/tmp/jobs/x/state.json",
    )

    dumped = record.model_dump(mode="json")

    assert dumped["kind"] == "background_task"
    assert dumped["live_state"] == "live"
