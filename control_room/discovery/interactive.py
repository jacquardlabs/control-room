"""Discover live interactive sessions from `~/.claude/sessions/*.json`.

Each file is written by the Claude Code CLI itself, one per running
process, keyed by pid (`<pid>.json`). This is the CLI's own live-process
bookkeeping -- not a cctx concept. The vendored cctx discovery module is
used only as a fallback/cross-check for `cwd` and `git_branch`, sourced
from the transcript itself, when the session file is missing or silent
on `cwd` (defensive: session files are the CLI's own bookkeeping, not a
contract control-room owns).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from control_room import paths
from control_room.gitmeta import resolve_worktree_info
from control_room.models import StreamKind, StreamRecord
from control_room.vendor import cctx_discovery


def discover_interactive_sessions(
    sessions_dir: Path,
    *,
    projects_dir: Path | None = None,
    now: datetime | None = None,
) -> list[StreamRecord]:
    """Return one StreamRecord per readable `<pid>.json` in `sessions_dir`.

    Liveness bookkeeping (`live_state`/`consecutive_misses`) is NOT set
    here -- that's `StreamRegistry`'s job, comparing across polls. This
    function only answers "what sessions does the CLI currently know
    about"; `pid_is_alive` below is the same-poll liveness probe the
    registry calls separately.
    """
    now = now or datetime.now(UTC)
    if not sessions_dir.is_dir():
        return []

    records = []
    for path in sorted(sessions_dir.glob("*.json")):
        record = _read_session_file(path, projects_dir=projects_dir, now=now)
        if record is not None:
            records.append(record)
    return records


def pid_is_alive(pid: int | None) -> bool:
    """Read-only liveness probe.

    Sending signal 0 checks a pid's existence/permission without affecting
    the target process at all (POSIX `kill(2)`) -- a probe, not an action.
    """
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just owned by someone else
    return True


def _read_session_file(
    path: Path, *, projects_dir: Path | None, now: datetime
) -> StreamRecord | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None

    session_id = raw.get("sessionId") or path.stem
    cwd = raw.get("cwd") or ""

    if not cwd:
        cwd, transcript_branch = _cwd_from_transcript(session_id, projects_dir)
    else:
        transcript_branch = None

    worktree_info = resolve_worktree_info(cwd) if cwd else None
    git_branch = (worktree_info.git_branch if worktree_info else None) or transcript_branch

    return StreamRecord(
        id=f"interactive:{session_id}",
        kind=StreamKind.INTERACTIVE,
        label=raw.get("name") or session_id,
        cwd=cwd,
        project_root=worktree_info.project_root if worktree_info else None,
        project_name=worktree_info.project_name if worktree_info else None,
        worktree_name=worktree_info.worktree_name if worktree_info else None,
        git_branch=git_branch,
        pid=raw.get("pid"),
        raw_status=raw.get("status"),
        first_seen=now,
        last_seen=now,
        source_path=str(path),
    )


def _cwd_from_transcript(session_id: str, projects_dir: Path | None) -> tuple[str, str | None]:
    """Fallback: recover cwd/branch from the transcript cctx already knows how to read.

    Only exercised when a session file lacks `cwd` -- every real session
    file observed while building this carried `cwd` directly, so this path
    is defensive, not the common case.
    """
    base = projects_dir or paths.projects_dir()
    for project in cctx_discovery.list_projects(base=base):
        for session in project.sessions:
            if session.session_id == session_id:
                return session.cwd or "", session.git_branch
    return "", None
