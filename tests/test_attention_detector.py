"""resolve_attention's precedence: died override > fresh hook > poll-fallback.

Also covers `poll_stream`'s per-kind dispatch -- the concrete meaning of
"poll-fallback covers streams that can't fire hooks" (issue #2's
acceptance criteria) for background jobs, and the reconciliation-on-restart
path for interactive sessions.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from control_room.attention.detector import STALE_AFTER, poll_stream, resolve_attention
from control_room.attention.models import AttentionEvent, AttentionSource, AttentionState
from control_room.models import LiveState, StreamKind, StreamRecord

NOW = datetime(2026, 7, 12, 14, 0, 0, tzinfo=UTC)


def _job_stream(source_path: Path, *, live_state: LiveState = LiveState.LIVE) -> StreamRecord:
    return StreamRecord(
        id="job:j1",
        kind=StreamKind.BACKGROUND_TASK,
        label="job",
        cwd="/tmp/proj",
        live_state=live_state,
        first_seen=NOW,
        last_seen=NOW,
        source_path=str(source_path),
    )


def test_died_override_wins_even_over_a_fresh_hook_event(tmp_path: Path) -> None:
    (tmp_path / "state.json").write_text(json.dumps({"state": "working"}), encoding="utf-8")
    stream = _job_stream(tmp_path / "state.json", live_state=LiveState.GRACE)
    fresh_hook = AttentionEvent(
        stream_id="job:j1", state=AttentionState.GRINDING, source=AttentionSource.HOOK, at=NOW
    )
    event = resolve_attention(
        stream, latest_hook_event=fresh_hook, previous_state=AttentionState.GRINDING, now=NOW
    )
    assert event.state == AttentionState.DIED


def test_fresh_hook_event_is_trusted_over_polling(tmp_path: Path) -> None:
    (tmp_path / "state.json").write_text(json.dumps({"state": "working"}), encoding="utf-8")
    stream = _job_stream(tmp_path / "state.json")
    fresh_hook = AttentionEvent(
        stream_id="job:j1", state=AttentionState.REVIEW_READY, source=AttentionSource.HOOK, at=NOW
    )
    event = resolve_attention(
        stream, latest_hook_event=fresh_hook, previous_state=AttentionState.GRINDING, now=NOW
    )
    assert event is fresh_hook  # unchanged, not re-derived from poll


def test_stale_hook_event_falls_back_to_polling(tmp_path: Path) -> None:
    (tmp_path / "state.json").write_text(json.dumps({"state": "done"}), encoding="utf-8")
    stream = _job_stream(tmp_path / "state.json")
    stale_hook = AttentionEvent(
        stream_id="job:j1",
        state=AttentionState.GRINDING,
        source=AttentionSource.HOOK,
        at=NOW - STALE_AFTER - timedelta(seconds=1),
    )
    event = resolve_attention(
        stream, latest_hook_event=stale_hook, previous_state=AttentionState.GRINDING, now=NOW
    )
    assert event.state == AttentionState.DONE
    assert event.source == AttentionSource.POLL


def test_no_hook_event_at_all_falls_back_to_polling_immediately(tmp_path: Path) -> None:
    (tmp_path / "state.json").write_text(json.dumps({"state": "done"}), encoding="utf-8")
    stream = _job_stream(tmp_path / "state.json")
    event = resolve_attention(
        stream, latest_hook_event=None, previous_state=AttentionState.GRINDING, now=NOW
    )
    assert event.state == AttentionState.DONE
    assert event.source == AttentionSource.POLL


# --- poll_stream dispatch by kind ---


def test_poll_stream_reads_job_state_json_directly(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"state": "done", "detail": "shipped"}), encoding="utf-8")
    stream = _job_stream(state_path)
    assert poll_stream(stream).state == AttentionState.DONE


def test_poll_stream_missing_job_state_file_degrades_to_grinding(tmp_path: Path) -> None:
    stream = _job_stream(tmp_path / "does-not-exist.json")
    assert poll_stream(stream).state == AttentionState.GRINDING


def test_poll_stream_resolves_interactive_transcript_for_reconciliation(tmp_path: Path) -> None:
    projects_dir = tmp_path / "projects"
    cwd = tmp_path / "my-project"
    encoded = str(cwd).replace("/", "-")
    project_dir = projects_dir / encoded
    project_dir.mkdir(parents=True)
    (project_dir / "sess-1.jsonl").write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "All done."}],
                    "stop_reason": "end_turn",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    stream = StreamRecord(
        id="interactive:sess-1",
        kind=StreamKind.INTERACTIVE,
        label="s",
        cwd=str(cwd),
        first_seen=NOW,
        last_seen=NOW,
        source_path=str(project_dir / "sess-1.jsonl"),
    )
    assert poll_stream(stream, projects_dir=projects_dir).state == AttentionState.REVIEW_READY


def test_poll_stream_unresolvable_interactive_transcript_degrades_to_grinding(
    tmp_path: Path,
) -> None:
    stream = StreamRecord(
        id="interactive:missing",
        kind=StreamKind.INTERACTIVE,
        label="s",
        cwd=str(tmp_path / "nonexistent-project"),
        first_seen=NOW,
        last_seen=NOW,
        source_path=str(tmp_path / "sessions" / "1.json"),
    )
    assert poll_stream(stream, projects_dir=tmp_path / "projects").state == AttentionState.GRINDING
