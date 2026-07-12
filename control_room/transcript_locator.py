"""Resolve a stream's underlying transcript JSONL path -- the parsing seam
issue #7 (cost-vitals) refers to as "the parsing seam decided in the
discovery story."

Extracted out of `control_room.attention.detector` (where this started life
as a private, interactive-only helper) rather than duplicated, per "prefer
reuse over creation": `attention-detection`'s poll-fallback and
`cost-vitals`'s per-stream burn computation both need the exact same
answer to "which `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl` file
is this stream's transcript" -- a second, independently-written resolver
here would be exactly the kind of interface drift the epic pre-mortem (#1,
#2) names as a risk.

Every real Claude Code stream -- interactive session or job/workflow run --
is, underneath, one Claude Code session with a `sessionId` and a `cwd`; the
transcript lives at `<projects_dir>/<encoded cwd>/<sessionId>.jsonl` either
way. The two `StreamKind`s just carry that `sessionId` differently:

- `interactive`: `stream.id` is `f"interactive:{session_id}"` (assigned by
  `discovery.interactive`) -- the session id is the identity itself.
- `background_task`/`workflow_run`: the job's own `state.json`
  (`stream.source_path`) carries a real `sessionId` field directly (the
  Claude Code CLI's own bookkeeping) -- `stream.id` is `f"job:{job_id}"`,
  where `job_id` is `daemonShort`, NOT the session id, so it has to be read
  off disk rather than parsed out of the stream id.
"""

from __future__ import annotations

import json
from pathlib import Path

from control_room.models import StreamKind, StreamRecord
from control_room.vendor.cctx_discovery import find_project_dir


def resolve_transcript_path(
    stream: StreamRecord, *, projects_dir: Path | None = None
) -> Path | None:
    """Return the transcript JSONL path for `stream`, or `None` if it can't
    be resolved (no cwd, no session id, no matching project dir, or the
    file doesn't exist yet) -- never a guess, matching every other
    poll-fallback path in this codebase (`transcripts.classify_transcript_tail`'s
    own docstring: uncertainty degrades, it doesn't fabricate).

    This is the *top-level* conversation only -- deliberate, not an
    oversight: `attention.detector`'s poll-fallback reasons about "the most
    recent turn," and a Task-dispatched subagent's own turns must never
    stand in for the parent stream's (the same reasoning `hook_events.py`
    already applies to hook-sourced events -- a subagent finishing must
    never flip the parent's attention state). Cost accounting has the
    opposite requirement -- real spend inside a dispatched subagent is
    still the parent stream's spend -- so it uses
    `resolve_all_transcript_paths` below instead of this function.
    """
    session_id = _session_id(stream)
    if session_id is None or not stream.cwd:
        return None

    project_dir = find_project_dir(Path(stream.cwd), base=projects_dir)
    if project_dir is None:
        return None

    candidate = project_dir / f"{session_id}.jsonl"
    return candidate if candidate.is_file() else None


def resolve_all_transcript_paths(
    stream: StreamRecord, *, projects_dir: Path | None = None
) -> tuple[Path, ...]:
    """Every transcript file real spend for `stream` was recorded into: the
    top-level conversation (`resolve_transcript_path`) plus any
    Task-dispatched subagent transcripts nested under Claude Code's own
    `<project_dir>/<session_id>/subagents/` directory (one level deeper
    still, `subagents/workflows/<run>/`, for workflow-dispatched agents --
    `rglob` catches both without caring which).

    Real spend inside a dispatched subagent is still spend the operator
    pays for on this stream -- unlike attention state (which a subagent
    must never influence, see `resolve_transcript_path`'s docstring),
    tokens/cost has no such exclusion. Verified against real
    `~/.claude/projects/*/*/subagents/**/*.jsonl` data while building this
    story: a session with `/work-through`-style subagent fan-out attributed
    the *majority* of its real cost to subagent files, not the top-level
    transcript -- omitting them here would undercount by more than the
    acceptance criteria's ~10% tolerance for exactly the workload
    (concurrent epics, dispatched worker fleets) this product's own
    persona centers on.

    Returns `()` (not a partial tuple) when the top-level transcript itself
    can't be resolved -- there is nothing to attribute a subagent directory
    to without it.
    """
    main = resolve_transcript_path(stream, projects_dir=projects_dir)
    if main is None:
        return ()

    subagents_dir = main.parent / main.stem / "subagents"
    if not subagents_dir.is_dir():
        return (main,)

    return (main, *sorted(subagents_dir.rglob("*.jsonl")))


def _session_id(stream: StreamRecord) -> str | None:
    if stream.kind is StreamKind.INTERACTIVE:
        return stream.id.removeprefix("interactive:")
    if stream.kind in (StreamKind.BACKGROUND_TASK, StreamKind.WORKFLOW_RUN):
        return _job_session_id(Path(stream.source_path))
    return None


def _job_session_id(state_path: Path) -> str | None:
    """Read a job's own `state.json` for its real `sessionId` -- the same
    file `attention.detector.poll_stream` already reads for that stream
    kind, just a different field off it."""
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    session_id = raw.get("sessionId")
    return session_id if isinstance(session_id, str) and session_id else None
