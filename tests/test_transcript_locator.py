"""`resolve_transcript_path`/`resolve_all_transcript_paths`: the shared
"which file is this stream's transcript" seam, used by both
`attention.detector`'s poll-fallback and `cost.usage`'s burn computation.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from control_room.models import LiveState, StreamKind, StreamRecord
from control_room.transcript_locator import resolve_all_transcript_paths, resolve_transcript_path

NOW = datetime(2026, 7, 12, 14, 0, 0, tzinfo=UTC)


def _encode(path: Path) -> str:
    return str(path.resolve()).replace("/", "-")


def _interactive_stream(cwd: Path, session_id: str) -> StreamRecord:
    return StreamRecord(
        id=f"interactive:{session_id}",
        kind=StreamKind.INTERACTIVE,
        label="s",
        cwd=str(cwd),
        live_state=LiveState.LIVE,
        first_seen=NOW,
        last_seen=NOW,
        source_path=str(cwd / "sessions" / "1.json"),
    )


def _job_stream(cwd: Path, source_path: Path, *, job_id: str = "j1") -> StreamRecord:
    return StreamRecord(
        id=f"job:{job_id}",
        kind=StreamKind.BACKGROUND_TASK,
        label="j",
        cwd=str(cwd),
        live_state=LiveState.LIVE,
        first_seen=NOW,
        last_seen=NOW,
        source_path=str(source_path),
    )


def _make_project(
    base: Path, cwd: Path, session_id: str, *, entries: list[dict] | None = None
) -> Path:
    project_dir = base / _encode(cwd)
    project_dir.mkdir(parents=True, exist_ok=True)
    transcript = project_dir / f"{session_id}.jsonl"
    lines = entries or [{"type": "user"}]
    transcript.write_text("\n".join(json.dumps(e) for e in lines) + "\n", encoding="utf-8")
    return transcript


def test_resolves_interactive_session_transcript_by_id_and_cwd(tmp_path):
    base = tmp_path / "projects"
    cwd = tmp_path / "proj"
    transcript = _make_project(base, cwd, "sid-1")
    stream = _interactive_stream(cwd, "sid-1")

    resolved = resolve_transcript_path(stream, projects_dir=base)

    assert resolved == transcript


def test_interactive_missing_project_dir_returns_none(tmp_path):
    stream = _interactive_stream(tmp_path / "nowhere", "sid-1")
    assert resolve_transcript_path(stream, projects_dir=tmp_path / "projects") is None


def test_interactive_missing_transcript_file_returns_none(tmp_path):
    base = tmp_path / "projects"
    cwd = tmp_path / "proj"
    (base / _encode(cwd)).mkdir(parents=True)
    stream = _interactive_stream(cwd, "sid-missing")
    assert resolve_transcript_path(stream, projects_dir=base) is None


def test_job_stream_resolves_via_its_own_sessionid_field(tmp_path):
    """A job's `state.json` -- not its `job:<id>` stream id -- carries the
    real session id the transcript is filed under (see
    `discovery.jobs`/`conftest.write_job`'s own `sessionId` field)."""
    base = tmp_path / "projects"
    cwd = tmp_path / "proj"
    transcript = _make_project(base, cwd, "the-real-session-id")

    state_path = tmp_path / "jobs" / "j1" / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({"sessionId": "the-real-session-id", "cwd": str(cwd)}))
    stream = _job_stream(cwd, state_path)

    resolved = resolve_transcript_path(stream, projects_dir=base)

    assert resolved == transcript


def test_job_stream_with_unreadable_state_json_returns_none(tmp_path):
    state_path = tmp_path / "jobs" / "j1" / "state.json"
    state_path.parent.mkdir(parents=True)
    # No file at all -- unreadable, not just missing sessionId.
    stream = _job_stream(tmp_path / "proj", state_path)
    assert resolve_transcript_path(stream, projects_dir=tmp_path / "projects") is None


def test_workflow_run_stream_resolves_the_same_way_as_background_task(tmp_path):
    base = tmp_path / "projects"
    cwd = tmp_path / "proj"
    transcript = _make_project(base, cwd, "wf-session")

    state_path = tmp_path / "jobs" / "w1" / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({"sessionId": "wf-session", "cwd": str(cwd)}))
    stream = StreamRecord(
        id="job:w1",
        kind=StreamKind.WORKFLOW_RUN,
        label="w",
        cwd=str(cwd),
        first_seen=NOW,
        last_seen=NOW,
        source_path=str(state_path),
    )

    assert resolve_transcript_path(stream, projects_dir=base) == transcript


def test_all_transcript_paths_is_just_the_main_file_with_no_subagents_dir(tmp_path):
    base = tmp_path / "projects"
    cwd = tmp_path / "proj"
    transcript = _make_project(base, cwd, "sid-1")
    stream = _interactive_stream(cwd, "sid-1")

    assert resolve_all_transcript_paths(stream, projects_dir=base) == (transcript,)


def test_all_transcript_paths_includes_nested_subagent_files(tmp_path):
    base = tmp_path / "projects"
    cwd = tmp_path / "proj"
    transcript = _make_project(base, cwd, "sid-1")
    project_dir = transcript.parent

    subagents_dir = project_dir / "sid-1" / "subagents"
    subagents_dir.mkdir(parents=True)
    agent_a = subagents_dir / "agent-a.jsonl"
    agent_a.write_text(json.dumps({"type": "user"}) + "\n", encoding="utf-8")

    # Workflow-dispatched agents nest one level deeper still.
    workflow_dir = subagents_dir / "workflows" / "wf_1"
    workflow_dir.mkdir(parents=True)
    agent_b = workflow_dir / "agent-b.jsonl"
    agent_b.write_text(json.dumps({"type": "user"}) + "\n", encoding="utf-8")

    stream = _interactive_stream(cwd, "sid-1")
    resolved = resolve_all_transcript_paths(stream, projects_dir=base)

    assert resolved == (transcript, agent_a, agent_b)


def test_all_transcript_paths_is_empty_when_main_transcript_unresolvable(tmp_path):
    stream = _interactive_stream(tmp_path / "nowhere", "sid-1")
    assert resolve_all_transcript_paths(stream, projects_dir=tmp_path / "projects") == ()
