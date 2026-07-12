"""Workflow-tool runs dispatched from inside a live session -- a distinct
on-disk shape from `discovery.jobs` (`<project>/<session>/workflows/<run>.json`,
never `~/.claude/jobs/`). Confirmed against a real, reported gap: a session
running two Workflow tool calls showed neither in control-room, only the one
interactive-session tab, because nothing scanned this path at all.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from control_room.discovery import workflows as workflows_module
from control_room.discovery.workflows import discover_session_workflows
from control_room.models import StreamKind
from tests.conftest import add_linked_worktree, make_main_repo, write_session_workflow


def test_discovers_one_record_per_workflow_run(tmp_path):
    write_session_workflow(
        tmp_path,
        project_dir_name="-proj",
        session_id="sess-1",
        cwd=str(tmp_path),
        run_id="wf_abc",
        workflow_name="epic-driver",
        status="running",
    )

    (record,) = discover_session_workflows(tmp_path)

    assert record.id == "workflow:wf_abc"
    assert record.kind == StreamKind.WORKFLOW_RUN
    assert record.label == "epic-driver"
    assert record.pid is None
    assert record.cwd == str(tmp_path)
    assert record.raw_status == "running"


def test_two_workflows_from_the_same_session_both_appear(tmp_path):
    """The exact reported gap: one session, two concurrent Workflow tool calls."""
    write_session_workflow(
        tmp_path, project_dir_name="-proj", session_id="sess-1", cwd=str(tmp_path), run_id="wf_one"
    )
    write_session_workflow(
        tmp_path, project_dir_name="-proj", session_id="sess-1", cwd=str(tmp_path), run_id="wf_two"
    )

    records = discover_session_workflows(tmp_path)

    assert sorted(r.id for r in records) == ["workflow:wf_one", "workflow:wf_two"]


def test_maps_to_worktree_via_the_dispatching_sessions_cwd(tmp_path):
    main_root = make_main_repo(tmp_path / "proj")
    worktree = add_linked_worktree(main_root, tmp_path / "proj-wt", name="wt", branch="feature")
    write_session_workflow(
        tmp_path / "claude-projects",
        project_dir_name="-proj-wt",
        session_id="sess-1",
        cwd=str(worktree),
        run_id="wf_abc",
    )

    (record,) = discover_session_workflows(tmp_path / "claude-projects")

    assert record.project_name == "proj"
    assert record.worktree_name == "wt"
    assert record.git_branch == "feature"


def test_none_projects_dir_returns_empty_never_the_real_tree() -> None:
    """Regression: `projects_dir=None` must be inert, not a fallback to
    `control_room.paths.projects_dir()`. A fallback here previously turned
    every existing test that doesn't pass `projects_dir` (most of them) into
    an unrequested scan of the real `~/.claude/projects` tree -- pure
    accidental coupling to whatever happens to be on the machine running the
    tests, not the isolation every other discoverer's tests already assume.
    """
    assert discover_session_workflows(None) == []


def test_missing_projects_dir_returns_empty(tmp_path):
    assert discover_session_workflows(tmp_path / "does-not-exist") == []


def test_a_run_finished_over_a_day_ago_is_not_rediscovered(tmp_path):
    """Regression: a Workflow-tool run's file is never cleaned up by the CLI
    (confirmed against a real machine: 51 such files accumulated, only 11
    from the last 24h) -- unfiltered, every historical run ever dispatched
    floods the wall the instant the server starts, unrelated to "is
    anything progressing right now."""
    path = write_session_workflow(
        tmp_path, project_dir_name="-proj", session_id="sess-1", cwd=str(tmp_path), run_id="wf_old"
    )
    old_time = (datetime.now(UTC) - timedelta(hours=25)).timestamp()
    os.utime(path, (old_time, old_time))

    assert discover_session_workflows(tmp_path) == []


def test_a_run_from_within_the_last_day_is_discovered(tmp_path):
    path = write_session_workflow(
        tmp_path,
        project_dir_name="-proj",
        session_id="sess-1",
        cwd=str(tmp_path),
        run_id="wf_recent",
    )
    recent_time = (datetime.now(UTC) - timedelta(hours=23)).timestamp()
    os.utime(path, (recent_time, recent_time))

    (record,) = discover_session_workflows(tmp_path)

    assert record.id == "workflow:wf_recent"


def test_malformed_workflow_json_is_skipped_not_raised(tmp_path):
    workflows_dir = tmp_path / "-proj" / "sess-1" / "workflows"
    workflows_dir.mkdir(parents=True)
    (workflows_dir / "wf_broken.json").write_text("{not json", encoding="utf-8")

    assert discover_session_workflows(tmp_path) == []


def test_unresolvable_session_defaults_to_empty_cwd_not_a_crash(tmp_path):
    """A workflow file whose dispatching session's own transcript can't be
    found (e.g. already pruned) degrades to an empty cwd -- same "no file, no
    guess" posture as every other discoverer here, never a raised error."""
    workflows_dir = tmp_path / "-proj" / "sess-unknown" / "workflows"
    workflows_dir.mkdir(parents=True)
    (workflows_dir / "wf_orphan.json").write_text(
        '{"runId": "wf_orphan", "workflowName": "x", "status": "running"}', encoding="utf-8"
    )

    (record,) = discover_session_workflows(tmp_path)

    assert record.cwd == ""
    assert record.project_root is None


def test_session_lookup_scans_once_per_poll_not_once_per_workflow_file(tmp_path, monkeypatch):
    """Regression: the first implementation called `cctx_discovery.list_projects`
    once per workflow file found, turning one poll into a multi-second stall
    against a real, many-session `~/.claude/projects` tree as soon as more
    than a handful of runs existed -- entirely self-inflicted, unrelated to
    how large `projects_dir` itself is. One scan must cover the whole call."""
    for i in range(5):
        write_session_workflow(
            tmp_path,
            project_dir_name="-proj",
            session_id="sess-1",
            cwd=str(tmp_path),
            run_id=f"wf_{i}",
        )

    calls = []
    real_list_projects = workflows_module.cctx_discovery.list_projects

    def counting_list_projects(*args, **kwargs):
        calls.append(1)
        return real_list_projects(*args, **kwargs)

    monkeypatch.setattr(workflows_module.cctx_discovery, "list_projects", counting_list_projects)

    records = discover_session_workflows(tmp_path)

    assert len(records) == 5
    assert len(calls) == 1
