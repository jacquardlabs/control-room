"""Combine hook-sourced events with poll-fallback into one current AttentionState per stream.

This is the integration point the design doc calls "hook-first, poll-
fallback" (issue #2's acceptance criteria: "poll-fallback covers streams
that can't fire hooks"): a hook-sourced event is trusted while fresh; once
stale (or for a stream kind that never fires hooks at all -- background
tasks and Workflow runs) poll-fallback takes over, reading the stream's own
disk state directly (job `state.json`, or transcript tail for interactive
sessions/reconciliation-on-restart).

Wiring this into an actual poll loop belongs to fleet-shell (issue #4);
this module only provides `resolve_attention`, the pure per-stream decision
fleet-shell's loop will call once per tick per stream.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from control_room.attention.jobs import classify_job_record
from control_room.attention.liveness import classify_liveness_transition
from control_room.attention.models import AttentionEvent, AttentionSource, AttentionState
from control_room.attention.transcripts import (
    TailVerdict,
    classify_transcript_tail,
    read_transcript_entries,
)
from control_room.models import StreamKind, StreamRecord
from control_room.vendor.cctx_discovery import find_project_dir

STALE_AFTER = timedelta(seconds=30)
"""How long a hook-sourced event stays authoritative before poll-fallback
takes over again. Generous relative to stream-discovery's own <=5s poll-
interval bar, so a live hook stream is never needlessly re-polled -- but
short enough that a hook which silently stopped firing (never registered,
or a future Claude Code hook-delivery change) doesn't leave a stream frozen
on a stale state forever.
"""


def resolve_attention(
    stream: StreamRecord,
    *,
    latest_hook_event: AttentionEvent | None,
    previous_state: AttentionState,
    now: datetime | None = None,
) -> AttentionEvent:
    """Return the current AttentionEvent for one stream.

    Precedence: (1) a liveness-driven `died` override always wins -- a
    stream that just lost its process mid-flight is `died` regardless of
    what a stale hook event or poll would otherwise say; (2) a fresh
    hook-sourced event, if one exists; (3) poll-fallback, read directly
    from the stream's own disk state.
    """
    now = now or datetime.now(UTC)

    died = classify_liveness_transition(previous_state, stream.live_state)
    if died is not None:
        return AttentionEvent(
            stream_id=stream.id, state=died, source=AttentionSource.POLL, at=now, detail="liveness"
        )

    if latest_hook_event is not None and (now - latest_hook_event.at) <= STALE_AFTER:
        return latest_hook_event

    verdict = poll_stream(stream)
    return AttentionEvent(
        stream_id=stream.id,
        state=verdict.state,
        reason=verdict.reason,
        source=AttentionSource.POLL,
        at=now,
    )


def poll_stream(stream: StreamRecord, *, projects_dir: Path | None = None) -> TailVerdict:
    """Poll-fallback for one stream, dispatched by kind.

    Background tasks/Workflow runs: re-read their own `state.json`
    (`stream.source_path`) and classify the self-reported `state` field --
    the only signal these streams have, since they can't fire hooks at all.

    Interactive sessions: resolve the transcript path from `cwd`/session id
    and classify its tail -- used for reconciliation on restart (before any
    hook has fired yet), not the primary path (that's hook-first, above).
    Never guesses: a transcript that can't be resolved degrades to
    `grinding`, same as an empty/missing transcript inside
    `transcripts.classify_transcript_tail` itself.

    `projects_dir` is injected (mirroring
    `discovery.interactive.discover_interactive_sessions`'s own
    `projects_dir` param) purely for test isolation from the real
    `~/.claude/projects` tree.
    """
    if stream.kind in (StreamKind.BACKGROUND_TASK, StreamKind.WORKFLOW_RUN):
        return classify_job_record(_read_json(Path(stream.source_path)))

    transcript_path = _resolve_transcript_path(stream, projects_dir=projects_dir)
    if transcript_path is None:
        return TailVerdict(AttentionState.GRINDING)
    return classify_transcript_tail(read_transcript_entries(transcript_path))


def _resolve_transcript_path(stream: StreamRecord, *, projects_dir: Path | None) -> Path | None:
    if not stream.cwd or not stream.id.startswith("interactive:"):
        return None
    session_id = stream.id.removeprefix("interactive:")
    project_dir = find_project_dir(Path(stream.cwd), base=projects_dir)
    if project_dir is None:
        return None
    candidate = project_dir / f"{session_id}.jsonl"
    return candidate if candidate.is_file() else None


def _read_json(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}
