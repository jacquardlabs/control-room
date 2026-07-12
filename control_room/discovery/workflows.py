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

Two functions, two distinct on-disk shapes of the *same* run over its
lifetime, confirmed directly against a real, live-in-flight run (2026-07):
`discover_session_workflows` reads a run's own `<run-id>.json` summary --
written exactly once, at completion (`result`/`durationMs`/`summary` are
all end-of-run-only fields; no such file on a real machine ever carried
`status: "running"`, even with a run actively in flight in another pane at
that exact moment). `discover_inflight_workflow_runs` is what actually
detects that in-flight case: a run's dispatched agents write to
`<session>/subagents/workflows/<run-id>/` well before any summary file
exists, and that directory's own `journal.jsonl` -- appended to at every
agent start/result, the same data the Workflow tool's own CLI progress
line reads -- is real, continuously-advancing evidence of life no static
status field could ever provide here. Both give the same run the same
`workflow:<run-id>` id, so a run discovered in-flight and later completed
is one continuous stream identity across that transition, never two.
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
        # `interactive:<session_id>` is exactly the id
        # `discover_interactive_sessions` gives the dispatching session's own
        # record -- the two discoverers already share this scheme
        # independently (session file `<pid>.json`'s own `sessionId`, here
        # the workflow file's own parent directory name), so no lookup is
        # needed to compute it, only to know it's even worth stating.
        parent_stream_id=f"interactive:{session_id}",
        pid=None,
        raw_status=raw.get("status"),
        first_seen=now,
        last_seen=now,
        source_path=str(path),
    )


def discover_inflight_workflow_runs(
    projects_dir: Path | None, *, now: datetime | None = None
) -> list[StreamRecord]:
    """Return one StreamRecord per Workflow run still in progress.

    Globbed one segment deeper than the completed-run shape --
    `*/*/subagents/workflows/*` -- since a still-running run's own agents
    write there well before any `<session>/workflows/<run-id>.json`
    summary exists (see this module's own docstring). A run directory with
    a matching completed-shape file is skipped here: it's finished, and
    `discover_session_workflows` above already owns it -- the two
    discoverers must never both produce a record for the same run-id in
    the same poll.

    Filtered to directories whose own newest file falls within `_MAX_AGE`,
    same constant and same reasoning as the completed-run filter above: an
    in-flight-*shaped* directory whose files haven't moved in over a day is
    functionally abandoned (its process died without ever writing a
    completion summary), and undiscovered is the right failure mode for
    that, not a fresh `live` tab flickering in on every server restart only
    to grind through several poll ticks of staleness before aging back out.

    `projects_dir=None` returns `[]` -- same isolation posture as
    `discover_session_workflows`.
    """
    now = now or datetime.now(UTC)
    if projects_dir is None or not projects_dir.is_dir():
        return []

    cutoff = (now - _MAX_AGE).timestamp()
    run_dirs = [d for d in sorted(projects_dir.glob("*/*/subagents/workflows/*")) if d.is_dir()]
    run_dirs = [d for d in run_dirs if inflight_workflow_activity_mtime(d) >= cutoff]
    if not run_dirs:
        return []

    session_locations = _session_locations(projects_dir)

    records = []
    for run_dir in run_dirs:
        record = _read_inflight_run(run_dir, session_locations=session_locations, now=now)
        if record is not None:
            records.append(record)
    return records


def inflight_workflow_activity_mtime(run_dir: Path) -> float:
    """Latest mtime across every file directly inside `run_dir` --
    `control_room.registry`'s own evidence-of-life signal for an in-flight
    run, and the age filter above.

    Unlike a completed run's one summary file (written once, frozen from
    the moment it's written), an in-flight run's own files genuinely
    advance while it's actually working: each dispatched agent writes its
    own transcript, and `journal.jsonl` is appended to at every agent
    start/result -- confirmed directly against a real, live run (2026-07):
    its newest file was 31 seconds old at the moment of inspection, with a
    fresh agent transcript actively streaming.
    """
    try:
        mtimes = [p.stat().st_mtime for p in run_dir.iterdir() if p.is_file()]
    except OSError:
        return 0.0
    return max(mtimes) if mtimes else 0.0


def _read_inflight_run(
    run_dir: Path, *, session_locations: dict[str, tuple[str, str | None]], now: datetime
) -> StreamRecord | None:
    run_id = run_dir.name
    session_id = run_dir.parent.parent.parent.name  # <session>/subagents/workflows/<run-id>
    completed_path = run_dir.parent.parent.parent / "workflows" / f"{run_id}.json"
    if completed_path.exists():
        return None  # finished -- discover_session_workflows owns it now

    cwd, git_branch = session_locations.get(session_id, ("", None))
    worktree_info = resolve_worktree_info(cwd) if cwd else None

    return StreamRecord(
        id=f"workflow:{run_id}",
        kind=StreamKind.WORKFLOW_RUN,
        label=_inflight_label(_read_progress(run_dir)),
        cwd=cwd,
        project_root=worktree_info.project_root if worktree_info else None,
        project_name=worktree_info.project_name if worktree_info else None,
        worktree_name=worktree_info.worktree_name if worktree_info else None,
        git_branch=worktree_info.git_branch if worktree_info else git_branch,
        parent_stream_id=f"interactive:{session_id}",
        pid=None,
        # No self-reported status exists at all while in flight (that's
        # the whole gap this function closes) -- `raw_status=None` degrades
        # `control_room.attention.jobs.classify_job_record` to `grinding`,
        # correctly: nothing here says anything is wrong.
        raw_status=None,
        first_seen=now,
        last_seen=now,
        source_path=str(run_dir),
    )


def _read_progress(run_dir: Path) -> tuple[int, int] | None:
    """(agents finished, agents started) from `journal.jsonl`'s own
    `started`/`result` entry counts -- the same data the Workflow tool's
    own CLI progress line ("25/26 agents done") reads, confirmed directly
    against a real run's journal. `None` if the journal can't be read or
    nothing has started yet."""
    try:
        lines = (run_dir / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    started = 0
    finished = 0
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == "started":
            started += 1
        elif entry.get("type") == "result":
            finished += 1
    return (finished, started) if started else None


def _inflight_label(progress: tuple[int, int] | None) -> str:
    if progress is None:
        return "workflow in progress"
    finished, started = progress
    return f"workflow in progress ({finished}/{started} agents)"
