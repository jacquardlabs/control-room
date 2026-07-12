"""Discover Workflow runs and background tasks from `~/.claude/jobs/*/state.json`.

Both kinds share one on-disk shape (a `~/.claude/jobs/<id>/state.json` plus
a `timeline.jsonl` event log); classification between them is a best-effort
guess -- see `classify_job_kind`'s docstring for the limitation.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from control_room.gitmeta import resolve_worktree_info
from control_room.models import StreamKind, StreamRecord


def discover_jobs(jobs_dir: Path, *, now: datetime | None = None) -> list[StreamRecord]:
    """Return one StreamRecord per readable `<id>/state.json` in `jobs_dir`.

    Non-directory entries alongside job dirs (`pins.json`, `.draft-*` files
    observed in practice) are skipped, not warned on -- they're the CLI's
    own bookkeeping, not malformed jobs.
    """
    now = now or datetime.now(UTC)
    if not jobs_dir.is_dir():
        return []

    records = []
    for entry in sorted(jobs_dir.iterdir()):
        if not entry.is_dir():
            continue
        record = _read_job(entry, now=now)
        if record is not None:
            records.append(record)
    return records


def classify_job_kind(raw: dict) -> StreamKind:
    """Best-effort kind classifier on Claude Code's own `template` field.

    LIMITATION (flagged for audit, not hidden): every real
    `~/.claude/jobs/*/state.json` inspected while building this (2026-07)
    carried `template: "bg"` -- including jobs whose own `detail`/`intent`
    text described running a multi-step "workflow." No on-disk example of
    a structurally distinct Workflow-run shape was available to verify
    against; `workflow_run` is reachable here only via a synthetic test
    fixture (`template: "workflow"`). Revisit once a real `/workflows`-style
    run's on-disk shape can be observed directly -- until then this
    defaults everything else to `background_task`, per DESIGN.md's
    "uncertainty degrades ... never to a false [signal]" spirit applied to
    classification, not just attention state.
    """
    if raw.get("template") == "workflow":
        return StreamKind.WORKFLOW_RUN
    return StreamKind.BACKGROUND_TASK


def job_activity_mtime(state_path: Path) -> float:
    """Latest mtime across a job's state file and its event log.

    This is the registry's evidence-of-life signal for jobs -- unlike
    interactive sessions, no pid is recorded in `state.json`, so liveness
    is inferred from whether the daemon has touched the job's files since
    the last poll, not from a process check.
    """
    candidates = (state_path, state_path.parent / "timeline.jsonl")
    mtimes = [p.stat().st_mtime for p in candidates if p.exists()]
    return max(mtimes) if mtimes else 0.0


def _read_job(job_dir: Path, *, now: datetime) -> StreamRecord | None:
    state_path = job_dir / "state.json"
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None

    job_id = raw.get("daemonShort") or job_dir.name
    cwd = raw.get("cwd") or raw.get("worktreePath") or raw.get("originCwd") or ""
    worktree_info = resolve_worktree_info(cwd) if cwd else None

    return StreamRecord(
        id=f"job:{job_id}",
        kind=classify_job_kind(raw),
        label=raw.get("name") or job_id,
        cwd=cwd,
        project_root=worktree_info.project_root if worktree_info else None,
        project_name=worktree_info.project_name if worktree_info else None,
        worktree_name=(worktree_info.worktree_name if worktree_info else raw.get("worktreeBranch")),
        git_branch=worktree_info.git_branch if worktree_info else raw.get("worktreeBranch"),
        pid=None,
        raw_status=raw.get("state"),
        first_seen=now,
        last_seen=now,
        source_path=str(state_path),
    )
