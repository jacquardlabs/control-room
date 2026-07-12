"""`AckRecord`/`AckStore`: persisted per-stream acknowledge + notify-dedup
bookkeeping -- issue #6's "ack state survives server restart" acceptance
criterion, verified here by literally constructing a second `AckStore`
against the same path and confirming it sees the first one's writes.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime

from control_room.attention.ack import AckRecord, AckStore
from control_room.attention.models import AttentionEvent, AttentionSource, AttentionState

_NOW = datetime(2026, 7, 12, tzinfo=UTC)


def _event(state: AttentionState, reason: str | None = None) -> AttentionEvent:
    return AttentionEvent(
        stream_id="s1", state=state, reason=reason, source=AttentionSource.POLL, at=_NOW
    )


def test_default_record_acknowledges_nothing() -> None:
    record = AckRecord()
    assert record.is_acknowledged(_event(AttentionState.GRINDING)) is False
    assert record.is_acknowledged(_event(AttentionState.PARKED, "r")) is False


def test_is_acknowledged_requires_both_state_and_reason_to_match() -> None:
    record = AckRecord(acknowledged_state=AttentionState.PARKED, acknowledged_reason="r1")
    assert record.is_acknowledged(_event(AttentionState.PARKED, "r1")) is True
    assert record.is_acknowledged(_event(AttentionState.PARKED, "r2")) is False
    assert record.is_acknowledged(_event(AttentionState.INPUT_BLOCKED, "r1")) is False


def test_get_returns_default_record_for_an_unknown_stream(tmp_path) -> None:
    store = AckStore(tmp_path / "ack-state.json")
    assert store.get("nope") == AckRecord()


def test_acknowledge_then_get_round_trips(tmp_path) -> None:
    store = AckStore(tmp_path / "ack-state.json")
    store.acknowledge("s1", state=AttentionState.PARKED, reason="NEEDS DISCUSSION")
    record = store.get("s1")
    assert record.acknowledged_state is AttentionState.PARKED
    assert record.acknowledged_reason == "NEEDS DISCUSSION"


def test_put_overwrites_the_whole_record(tmp_path) -> None:
    store = AckStore(tmp_path / "ack-state.json")
    store.acknowledge("s1", state=AttentionState.PARKED, reason="r")
    store.put("s1", AckRecord(last_notified_state=AttentionState.PARKED, last_notified_reason="r"))
    record = store.get("s1")
    assert record.acknowledged_state is None  # overwritten, not merged
    assert record.last_notified_state is AttentionState.PARKED


def test_forget_drops_a_streams_record(tmp_path) -> None:
    store = AckStore(tmp_path / "ack-state.json")
    store.acknowledge("s1", state=AttentionState.PARKED, reason="r")
    store.forget("s1")
    assert store.get("s1") == AckRecord()


def test_forget_on_an_absent_stream_is_a_no_op(tmp_path) -> None:
    store = AckStore(tmp_path / "ack-state.json")
    store.forget("never-existed")  # must not raise


def test_prune_drops_only_stale_ids(tmp_path) -> None:
    store = AckStore(tmp_path / "ack-state.json")
    store.acknowledge("keep", state=AttentionState.PARKED, reason="r")
    store.acknowledge("drop", state=AttentionState.PARKED, reason="r")
    store.prune({"keep"})
    assert store.get("keep").acknowledged_state is AttentionState.PARKED
    assert store.get("drop") == AckRecord()


def test_ack_state_survives_a_simulated_restart(tmp_path) -> None:
    """The acceptance criterion, literally: a second `AckStore` against the
    same path (standing in for a fresh server process after a restart) sees
    the first one's acknowledged state."""
    path = tmp_path / "ack-state.json"
    first = AckStore(path)
    first.acknowledge("s1", state=AttentionState.PARKED, reason="NEEDS DISCUSSION")

    restarted = AckStore(path)
    record = restarted.get("s1")
    assert record.acknowledged_state is AttentionState.PARKED
    assert record.acknowledged_reason == "NEEDS DISCUSSION"


def test_missing_file_loads_as_empty_not_an_error(tmp_path) -> None:
    store = AckStore(tmp_path / "does-not-exist.json")
    assert store.get("s1") == AckRecord()


def test_corrupt_file_degrades_to_empty_rather_than_crashing(tmp_path) -> None:
    path = tmp_path / "ack-state.json"
    path.write_text("{not valid json", encoding="utf-8")
    store = AckStore(path)
    assert store.get("s1") == AckRecord()


def test_one_corrupt_entry_does_not_blind_the_whole_store(tmp_path) -> None:
    path = tmp_path / "ack-state.json"
    path.write_text(
        json.dumps({"good": {"acknowledged_state": "parked"}, "bad": {"acknowledged_state": 123}}),
        encoding="utf-8",
    )
    store = AckStore(path)
    assert store.get("good").acknowledged_state is AttentionState.PARKED
    assert store.get("bad") == AckRecord()


def test_no_tmp_file_left_behind_after_a_save(tmp_path) -> None:
    path = tmp_path / "ack-state.json"
    store = AckStore(path)
    store.acknowledge("s1", state=AttentionState.PARKED, reason="r")
    assert path.exists()
    assert not path.with_suffix(path.suffix + ".tmp").exists()


def test_concurrent_writes_from_multiple_threads_never_corrupt_the_store(tmp_path) -> None:
    """`AckStore` is written from two different threads in the real server
    (the poll loop's notify-dedup bookkeeping and the `/ack` HTTP handler) --
    this drives many concurrent acknowledges and asserts the store survives
    with every stream's write intact, never a torn/corrupt file."""
    path = tmp_path / "ack-state.json"
    store = AckStore(path)

    def _ack(stream_id: str) -> None:
        for _ in range(20):
            store.acknowledge(stream_id, state=AttentionState.PARKED, reason=f"r-{stream_id}")

    threads = [threading.Thread(target=_ack, args=(f"s{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for i in range(8):
        record = store.get(f"s{i}")
        assert record.acknowledged_state is AttentionState.PARKED
        assert record.acknowledged_reason == f"r-s{i}"

    # The file on disk must also parse cleanly and agree with in-memory state.
    reloaded = AckStore(path)
    for i in range(8):
        assert reloaded.get(f"s{i}").acknowledged_reason == f"r-s{i}"
