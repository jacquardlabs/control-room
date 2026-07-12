"""Discover Workflow-tool runs dispatched from inside a live session.

A distinct on-disk shape from `control_room.discovery.jobs`: a run started
via the Workflow tool is tracked at
`<project>/<session-id>/workflows/<run-id>.json`, nested under the session
that dispatched it -- not under `~/.claude/jobs/`, which `discovery.jobs`
already covers (the CLI's own daemon-launched background/workflow jobs).
These are two genuinely different mechanisms with two different file
shapes; `discovery.jobs`' own docstring already flagged that no real
Workflow-run shape had been observed while it was built. This one has been,
confirmed live (2026-07) against this project's own `epic-driver` Workflow
runs, several sessions deep -- and against a real, reported gap: a session
running two Workflow tool calls showed neither in control-room, only the
one interactive-session tab, because nothing scanned this path at all.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from control_room.gitmeta import resolve_worktree_info
from control_room.models import StreamKind, StreamRecord
from control_room.vendor import cctx_discovery

_MAX_AGE = timedelta(hours=24)
"""A Workflow-tool run's file is never cleaned up by the CLI -- unlike
`~/.claude/jobs/` (2 entries, real machine, 2026-07), a real
`~/.claude/projects` tree accumulates these indefinitely (51 found on one
development machine, only 11 from the last 24h, only 3 from the last 4h).
Undiscovered isn't the same failure mode as never-aging-out: this floods
the wall with historical noise the instant the server starts, unrelated to
"is anything progressing right now" -- the one thing the product exists to
answer. 24h matches the wall's own "burn today" framing rather than
introducing a second, arbitrary notion of "recent." A run outside this
window that's still somehow live (status non-terminal, file still being
touched) is the one case worth naming explicitly: it stays invisible until
its next write brings its mtime back inside the window -- accepted, since
a Workflow run silently active for over a day with no fresher touch than
that would be unusual enough to warrant looking at the file directly.
"""


def discover_session_workflows(
    projects_dir: Path | None, *, now: datetime | None = None
) -> list[StreamRecord]:
    """Return one StreamRecord per readable, recent `<project>/<session>/workflows/<run>.json`.

    Globbed two segments deep under `projects_dir` (`*/*/workflows/*.json`)
    -- deep enough to reach every live session's own workflow runs, never
    deep enough to wander into a run's own subagent transcripts alongside
    it (those live one directory over, under `subagents/workflows/`).
    Filtered to files modified within `_MAX_AGE` (see its own docstring).

    `projects_dir=None` returns `[]` -- deliberately no fallback to
    `control_room.paths.projects_dir()` here. `control_room.shell.server`'s
    `build_server` already resolves the real path before constructing
    anything downstream, so production always has a real value by the time
    it reaches here; a caller (a test, a script) that constructs
    `StreamRegistry`/`FleetState` directly without naming one gets inert
    behavior instead of an unrequested scan of the real `~/.claude`
    tree -- the same isolation every other discoverer's test suite already
    assumes, made structural instead of convention-dependent here.
    """
    now = now or datetime.now(UTC)
    if projects_dir is None or not projects_dir.is_dir():
        return []
    base = projects_dir

    cutoff = (now - _MAX_AGE).timestamp()
    paths_found = [
        p for p in sorted(base.glob("*/*/workflows/*.json")) if p.stat().st_mtime >= cutoff
    ]
    if not paths_found:
        return []

    # One full scan for the whole poll, not one per file found: a
    # dispatching session's cwd/branch is looked up by id below, and
    # `cctx_discovery.list_projects` is its own bounded-but-real disk scan
    # (~25ms across a real ~400-session ~/.claude/projects tree, measured
    # 2026-07) -- calling it once per workflow file turned one poll tick
    # into a multi-second stall as soon as more than a handful of runs
    # existed, entirely self-inflicted and unrelated to how large
    # `projects_dir` itself is.
    session_locations = _session_locations(base)

    records = []
    for path in paths_found:
        record = _read_workflow_file(path, session_locations=session_locations, now=now)
        if record is not None:
            records.append(record)
    return records


def _session_locations(projects_dir: Path) -> dict[str, tuple[str, str | None]]:
    """Every known session's own (cwd, git_branch), keyed by session id --
    built once per poll and handed to every workflow file found in it."""
    locations: dict[str, tuple[str, str | None]] = {}
    for project in cctx_discovery.list_projects(base=projects_dir):
        for session in project.sessions:
            locations[session.session_id] = (session.cwd or "", session.git_branch)
    return locations


def _read_workflow_file(
    path: Path, *, session_locations: dict[str, tuple[str, str | None]], now: datetime
) -> StreamRecord | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None

    run_id = raw.get("runId") or path.stem
    session_id = path.parent.parent.name
    cwd, git_branch = session_locations.get(session_id, ("", None))
    worktree_info = resolve_worktree_info(cwd) if cwd else None

    return StreamRecord(
        id=f"workflow:{run_id}",
        kind=StreamKind.WORKFLOW_RUN,
        label=raw.get("workflowName") or run_id,
        cwd=cwd,
        project_root=worktree_info.project_root if worktree_info else None,
        project_name=worktree_info.project_name if worktree_info else None,
        worktree_name=worktree_info.worktree_name if worktree_info else None,
        git_branch=worktree_info.git_branch if worktree_info else git_branch,
        pid=None,
        raw_status=raw.get("status"),
        first_seen=now,
        last_seen=now,
        source_path=str(path),
    )
