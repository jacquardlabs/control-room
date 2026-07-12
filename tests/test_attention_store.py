"""EventLogStore: the append-only hand-off between the hook script and the poller."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from control_room.attention.models import AttentionEvent, AttentionSource, AttentionState
from control_room.attention.store import EventLogStore

NOW = datetime(2026, 7, 12, tzinfo=UTC)


def test_append_then_latest_roundtrips(tmp_path: Path) -> None:
    store = EventLogStore(tmp_path)
    event = AttentionEvent(
        stream_id="interactive:abc",
        state=AttentionState.GRINDING,
        source=AttentionSource.HOOK,
        at=NOW,
    )
    store.append(event)
    assert store.latest("interactive:abc") == event


def test_latest_returns_the_most_recent_of_several_appends(tmp_path: Path) -> None:
    store = EventLogStore(tmp_path)
    store.append(
        AttentionEvent(
            stream_id="s1", state=AttentionState.GRINDING, source=AttentionSource.HOOK, at=NOW
        )
    )
    later = AttentionEvent(
        stream_id="s1", state=AttentionState.REVIEW_READY, source=AttentionSource.HOOK, at=NOW
    )
    store.append(later)
    assert store.latest("s1") == later


def test_latest_for_unknown_stream_is_none(tmp_path: Path) -> None:
    assert EventLogStore(tmp_path).latest("never-seen") is None


def test_streams_get_separate_logs_no_interleaving(tmp_path: Path) -> None:
    store = EventLogStore(tmp_path)
    a = AttentionEvent(
        stream_id="stream-a", state=AttentionState.GRINDING, source=AttentionSource.HOOK, at=NOW
    )
    b = AttentionEvent(
        stream_id="stream-b", state=AttentionState.DONE, source=AttentionSource.POLL, at=NOW
    )
    store.append(a)
    store.append(b)
    assert store.latest("stream-a") == a
    assert store.latest("stream-b") == b


def test_malformed_trailing_line_falls_back_to_last_good_one(tmp_path: Path) -> None:
    store = EventLogStore(tmp_path)
    good = AttentionEvent(
        stream_id="s1", state=AttentionState.GRINDING, source=AttentionSource.HOOK, at=NOW
    )
    store.append(good)
    # simulate a partial write mid-flush
    path = tmp_path / "s1.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"stream_id": "s1", "state": "gr')
    assert store.latest("s1") == good


def test_stream_id_with_slash_is_sanitized_to_a_safe_filename(tmp_path: Path) -> None:
    store = EventLogStore(tmp_path)
    event = AttentionEvent(
        stream_id="job:foo/bar", state=AttentionState.GRINDING, source=AttentionSource.POLL, at=NOW
    )
    store.append(event)
    assert store.latest("job:foo/bar") == event
    assert not (
        tmp_path / "job:foo"
    ).exists()  # would exist if unsanitized "/" were treated as a subdir
