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


_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "transcripts"


def test_stale_input_blocked_hook_is_not_declassified_to_grinding_by_poll(
    monkeypatch, tmp_path: Path
) -> None:
    """Regression for the acceptance-gate finding: `input-blocked` is the
    ONE amber state poll-fallback can never re-derive (a mid-tool-call
    transcript tail is deliberately `grinding` -- see
    `transcripts.classify_transcript_tail`'s adversarial case -- and a
    permission prompt has no other on-disk signal poll can read). Once a
    confirmed `input-blocked` hook event goes stale, unqualified
    `STALE_AFTER` would let poll silently override it with a
    less-informative `grinding`, dropping a still-pending needs-you moment.
    A stale `input-blocked` hook event must keep winning until a new hook
    event (a resume signal) supersedes it.
    """
    projects_dir = tmp_path / "projects"
    cwd = tmp_path / "my-project"
    encoded = str(cwd).replace("/", "-")
    project_dir = projects_dir / encoded
    project_dir.mkdir(parents=True)
    fixture = _FIXTURES_DIR / "grinding__adversarial_mid_tool_call.jsonl"
    (project_dir / "sess-1.jsonl").write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("CCTX_PROJECTS_DIR", str(projects_dir))

    stream = StreamRecord(
        id="interactive:sess-1",
        kind=StreamKind.INTERACTIVE,
        label="s",
        cwd=str(cwd),
        first_seen=NOW,
        last_seen=NOW,
        source_path=str(project_dir / "sess-1.jsonl"),
    )

    # Sanity check: poll alone (no hook in play) really does give grinding
    # for this fixture -- confirming poll genuinely cannot re-derive
    # input-blocked from this transcript, the premise the finding relies on.
    assert poll_stream(stream, projects_dir=projects_dir).state == AttentionState.GRINDING

    stale_input_blocked = AttentionEvent(
        stream_id="interactive:sess-1",
        state=AttentionState.INPUT_BLOCKED,
        reason="Permission needed for command: pytest -q",
        source=AttentionSource.HOOK,
        at=NOW - STALE_AFTER - timedelta(seconds=1),
    )

    event = resolve_attention(
        stream,
        latest_hook_event=stale_input_blocked,
        previous_state=AttentionState.INPUT_BLOCKED,
        now=NOW,
    )

    assert event.state == AttentionState.INPUT_BLOCKED
    assert event.source == AttentionSource.HOOK
    assert event.reason == "Permission needed for command: pytest -q"


def test_stale_non_input_blocked_hook_still_falls_back_to_polling(tmp_path: Path) -> None:
    """The STALE_AFTER exemption is narrow: a stale `grinding` hook event
    (not `input-blocked`) must still fall back to polling as before --
    only `input-blocked` is exempt, since it's the only amber poll can't
    re-derive."""
    (tmp_path / "state.json").write_text(json.dumps({"state": "done"}), encoding="utf-8")
    stream = _job_stream(tmp_path / "state.json")
    stale_grinding = AttentionEvent(
        stream_id="job:j1",
        state=AttentionState.GRINDING,
        source=AttentionSource.HOOK,
        at=NOW - STALE_AFTER - timedelta(seconds=1),
    )
    event = resolve_attention(
        stream, latest_hook_event=stale_grinding, previous_state=AttentionState.GRINDING, now=NOW
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
