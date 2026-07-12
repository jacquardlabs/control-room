"""Building a BoardView for a stream with no board protocol -- generic vitals only,
straight from stream-discovery/attention-detection's own output shapes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

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
    assert instrument.verdict_trail == ()


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


# ---------------------------------------------------------------------------
# A Workflow run's own dispatched-agent results as a verdict_trail --
# DESIGN.md's drawer, generic-adapter side (the protocol counterpart lives
# in test_board_protocol_adapter.py).
# ---------------------------------------------------------------------------


def _write_journal(run_dir: Path, lines: list[dict]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "journal.jsonl").write_text(
        "\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8"
    )


def test_completed_workflow_run_gets_its_subagents_verdict_trail(tmp_path: Path) -> None:
    """A completed run's `source_path` is its own summary file
    (`<session>/workflows/<run-id>.json`); the subagent journal lives one
    directory over, at `<session>/subagents/workflows/<run-id>/` -- derived,
    never a second source of truth for the run id/session."""
    session_dir = tmp_path / "sess-1"
    (session_dir / "workflows").mkdir(parents=True)
    source_path = session_dir / "workflows" / "wf_abc.json"
    source_path.write_text("{}", encoding="utf-8")
    _write_journal(
        session_dir / "subagents" / "workflows" / "wf_abc",
        [
            {"type": "started", "agentId": "agent1234"},
            {
                "type": "result",
                "agentId": "agent1234",
                "result": {"summary": "did it", "sha": "abc123"},
            },
        ],
    )
    stream = _stream(
        id="workflow:wf_abc",
        kind=StreamKind.WORKFLOW_RUN,
        source_path=str(source_path),
    )
    event = AttentionEvent(
        stream_id=stream.id, state=AttentionState.DONE, source=AttentionSource.POLL, at=_NOW
    )

    view = build_generic_board(stream, event)

    (entry,) = view.instruments[0].verdict_trail
    assert entry.step == "agent123"
    assert entry.outcome == "did it"
    assert entry.sha == "abc123"


def test_inflight_workflow_run_gets_its_subagents_verdict_trail(tmp_path: Path) -> None:
    """An in-flight run's `source_path` is already the run's own directory
    (`discover_inflight_workflow_runs` sets it that way) -- no derivation
    needed."""
    run_dir = tmp_path / "sess-1" / "subagents" / "workflows" / "wf_live"
    _write_journal(
        run_dir,
        [
            {"type": "started", "agentId": "agent5678"},
        ],
    )
    stream = _stream(
        id="workflow:wf_live",
        kind=StreamKind.WORKFLOW_RUN,
        source_path=str(run_dir),
    )
    event = AttentionEvent(
        stream_id=stream.id, state=AttentionState.GRINDING, source=AttentionSource.POLL, at=_NOW
    )

    view = build_generic_board(stream, event)

    (entry,) = view.instruments[0].verdict_trail
    assert entry.outcome == "in progress"


def test_non_workflow_run_kinds_never_get_a_subagent_verdict_trail(tmp_path: Path) -> None:
    """An interactive session or background task has no dispatched-agent
    journal concept at all -- always an empty trail, regardless of what
    happens to exist on disk at its own source_path."""
    stream = _stream(kind=StreamKind.INTERACTIVE, source_path=str(tmp_path / "irrelevant.json"))
    event = AttentionEvent(
        stream_id=stream.id, state=AttentionState.GRINDING, source=AttentionSource.POLL, at=_NOW
    )
    view = build_generic_board(stream, event)
    assert view.instruments[0].verdict_trail == ()


def test_workflow_run_with_no_journal_yet_has_an_empty_trail_not_a_crash(tmp_path: Path) -> None:
    source_path = tmp_path / "sess-1" / "workflows" / "wf_new.json"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("{}", encoding="utf-8")
    stream = _stream(
        id="workflow:wf_new", kind=StreamKind.WORKFLOW_RUN, source_path=str(source_path)
    )
    event = AttentionEvent(
        stream_id=stream.id, state=AttentionState.GRINDING, source=AttentionSource.POLL, at=_NOW
    )
    view = build_generic_board(stream, event)
    assert view.instruments[0].verdict_trail == ()
