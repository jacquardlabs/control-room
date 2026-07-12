"""Shared fixture builders for stream-discovery tests.

All fixtures build plain directories/files by hand (git's own on-disk
formats, the CLI's own JSON shapes) rather than shelling out to `git init`
or spawning real Claude Code processes -- discovery is pure disk-reading,
so plain fixtures are enough, except where a real pid is the thing under
test (see test_registry.py's use of subprocess for the "killed session"
scenario).
"""

from __future__ import annotations

import json
from pathlib import Path


def make_main_repo(root: Path, *, branch: str = "main") -> Path:
    """Build a `.git`-as-directory main tree at `root`, with `HEAD` on `branch`."""
    git_dir = root / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")
    return root


def add_linked_worktree(main_root: Path, worktree_root: Path, *, name: str, branch: str) -> Path:
    """Build a linked worktree at `worktree_root`, pointed at `main_root`'s `.git`.

    Mirrors real git's shape exactly:
      <worktree_root>/.git                         -> "gitdir: <main>/.git/worktrees/<name>"
      <main>/.git/worktrees/<name>/commondir        -> "../.." (relative to itself)
      <main>/.git/worktrees/<name>/gitdir           -> "<worktree_root>/.git"
      <main>/.git/worktrees/<name>/HEAD             -> "ref: refs/heads/<branch>"
    """
    main_git_dir = main_root / ".git"
    worktrees_entry = main_git_dir / "worktrees" / name
    worktrees_entry.mkdir(parents=True)

    worktree_root.mkdir(parents=True, exist_ok=True)
    (worktree_root / ".git").write_text(f"gitdir: {worktrees_entry}\n", encoding="utf-8")

    (worktrees_entry / "commondir").write_text("../..\n", encoding="utf-8")
    (worktrees_entry / "gitdir").write_text(f"{worktree_root / '.git'}\n", encoding="utf-8")
    (worktrees_entry / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")
    return worktree_root


def write_session_file(
    sessions_dir: Path,
    *,
    pid: int,
    session_id: str,
    cwd: str,
    name: str = "session",
    status: str = "busy",
    version: str = "2.1.207",
) -> Path:
    sessions_dir.mkdir(parents=True, exist_ok=True)
    path = sessions_dir / f"{pid}.json"
    payload = {
        "pid": pid,
        "sessionId": session_id,
        "cwd": cwd,
        "startedAt": 1783858135486,
        "procStart": "Sun Jul 12 12:08:54 2026",
        "version": version,
        "peerProtocol": 1,
        "kind": "interactive",
        "entrypoint": "cli",
        "name": name,
        "updatedAt": 1783861146182,
        "status": status,
        "statusUpdatedAt": 1783861146182,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def write_job(
    jobs_dir: Path,
    *,
    job_id: str,
    cwd: str,
    name: str = "job",
    state: str = "working",
    template: str = "bg",
    worktree_path: str | None = None,
    worktree_branch: str | None = None,
) -> Path:
    job_dir = jobs_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "state": state,
        "detail": "doing the thing",
        "tempo": "active",
        "inFlight": {"tasks": 1, "queued": 0, "kinds": ["bash"]},
        "tokens": 12345,
        "template": template,
        "intent": "do it",
        "name": name,
        "nameSource": "user",
        "sessionId": f"{job_id}-session",
        "resumeSessionId": f"{job_id}-session",
        "daemonShort": job_id,
        "cliVersion": "2.1.207",
        "cwd": cwd,
    }
    if worktree_path is not None:
        payload["worktreePath"] = worktree_path
    if worktree_branch is not None:
        payload["worktreeBranch"] = worktree_branch
    (job_dir / "state.json").write_text(json.dumps(payload), encoding="utf-8")
    (job_dir / "timeline.jsonl").write_text(
        json.dumps({"at": "2026-07-12T12:00:00.000Z", "state": state, "detail": "", "text": ""})
        + "\n",
        encoding="utf-8",
    )
    return job_dir / "state.json"


def _write_session_transcript(
    project_dir: Path, *, session_id: str, cwd: str, git_branch: str | None
) -> None:
    """The one line of transcript `cctx_discovery` needs to resolve a
    session's own cwd/branch -- shared by every fixture builder below that
    needs a dispatching session to be resolvable."""
    project_dir.mkdir(parents=True, exist_ok=True)
    transcript_entry = {
        "sessionId": session_id,
        "cwd": cwd,
        "timestamp": "2026-07-12T12:00:00.000Z",
    }
    if git_branch is not None:
        transcript_entry["gitBranch"] = git_branch
    (project_dir / f"{session_id}.jsonl").write_text(
        json.dumps(transcript_entry) + "\n", encoding="utf-8"
    )


def write_session_workflow(
    projects_dir: Path,
    *,
    project_dir_name: str,
    session_id: str,
    cwd: str,
    run_id: str,
    workflow_name: str = "epic-driver",
    status: str = "running",
    git_branch: str | None = None,
) -> Path:
    """Build a session transcript (enough for `cctx_discovery` to resolve its
    cwd/branch) plus one Workflow-tool run file nested under it, matching the
    real on-disk shape: `<projects_dir>/<project>/<session_id>.jsonl` (the
    transcript) and `<projects_dir>/<project>/<session_id>/workflows/<run_id>.json`
    (the run) -- confirmed against real `~/.claude/projects` data, 2026-07.
    """
    project_dir = projects_dir / project_dir_name
    _write_session_transcript(project_dir, session_id=session_id, cwd=cwd, git_branch=git_branch)

    workflows_dir = project_dir / session_id / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "runId": run_id,
        "workflowName": workflow_name,
        "status": status,
        "startTime": 1783876394416,
    }
    path = workflows_dir / f"{run_id}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def write_inflight_workflow(
    projects_dir: Path,
    *,
    project_dir_name: str,
    session_id: str,
    cwd: str,
    run_id: str,
    started: int = 1,
    finished: int = 0,
    git_branch: str | None = None,
) -> Path:
    """Build a session transcript plus a still-in-progress Workflow run's own
    `subagents/workflows/<run_id>/journal.jsonl` -- the shape a run has
    *before* its `workflows/<run_id>.json` completion summary exists,
    confirmed against a real, live-in-flight run (2026-07): `started` real
    entries followed by `finished` matching `result` entries, one
    unmatched `started` left over whenever `finished < started` (the
    currently-in-flight agent), matching `discover_inflight_workflow_runs`'
    own started/result counting.
    """
    project_dir = projects_dir / project_dir_name
    _write_session_transcript(project_dir, session_id=session_id, cwd=cwd, git_branch=git_branch)

    run_dir = project_dir / session_id / "subagents" / "workflows" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    for i in range(started):
        lines.append(json.dumps({"type": "started", "agentId": f"agent-{i}"}))
        if i < finished:
            lines.append(json.dumps({"type": "result", "agentId": f"agent-{i}"}))
    journal_path = run_dir / "journal.jsonl"
    journal_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return run_dir
