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
from control_room.discovery.workflows import (
    discover_inflight_workflow_runs,
    discover_session_workflows,
    inflight_workflow_activity_mtime,
)
from control_room.models import StreamKind
from tests.conftest import (
    add_linked_worktree,
    make_main_repo,
    write_inflight_workflow,
    write_session_workflow,
)


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
    assert record.parent_stream_id == "interactive:sess-1"


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
    # parent_stream_id comes straight from the file's own path, independent
    # of whether the session's cwd/branch could be resolved.
    assert record.parent_stream_id == "interactive:sess-unknown"


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


# ---------------------------------------------------------------------------
# discover_inflight_workflow_runs -- a run before its completion summary
# exists, confirmed against a real, live-in-flight run (2026-07): its own
# `subagents/workflows/<run-id>/journal.jsonl` is what carries evidence of
# life and progress while `discover_session_workflows` above still sees
# nothing at all for it.
# ---------------------------------------------------------------------------


def test_discovers_an_inflight_run_with_no_completion_summary(tmp_path):
    write_inflight_workflow(
        tmp_path,
        project_dir_name="-proj",
        session_id="sess-1",
        cwd=str(tmp_path),
        run_id="wf_live",
        started=26,
        finished=25,
    )

    (record,) = discover_inflight_workflow_runs(tmp_path)

    assert record.id == "workflow:wf_live"
    assert record.kind == StreamKind.WORKFLOW_RUN
    assert record.parent_stream_id == "interactive:sess-1"
    assert record.cwd == str(tmp_path)
    assert record.raw_status is None
    assert "25/26 agents" in record.label


def test_a_run_with_a_completion_summary_is_not_rediscovered_as_inflight(tmp_path):
    """The exact rule preventing the two discoverers from ever both
    producing a record for the same run-id: once
    `<session>/workflows/<run-id>.json` exists, the run is finished and
    `discover_session_workflows` owns it -- the in-flight path must yield
    nothing for it, even though its `subagents/workflows/<run-id>/`
    directory is never cleaned up."""
    write_inflight_workflow(
        tmp_path,
        project_dir_name="-proj",
        session_id="sess-1",
        cwd=str(tmp_path),
        run_id="wf_done",
        started=3,
        finished=3,
    )
    write_session_workflow(
        tmp_path,
        project_dir_name="-proj",
        session_id="sess-1",
        cwd=str(tmp_path),
        run_id="wf_done",
        status="completed",
    )

    assert discover_inflight_workflow_runs(tmp_path) == []
    (record,) = discover_session_workflows(tmp_path)
    assert record.id == "workflow:wf_done"


def test_progress_label_reflects_started_and_result_counts(tmp_path):
    write_inflight_workflow(
        tmp_path,
        project_dir_name="-proj",
        session_id="sess-1",
        cwd=str(tmp_path),
        run_id="wf_a",
        started=3,
        finished=1,
    )

    (record,) = discover_inflight_workflow_runs(tmp_path)

    assert record.label == "workflow in progress (1/3 agents)"


def test_no_started_entries_yields_the_generic_label_not_zero_of_zero(tmp_path):
    """A run directory that exists but whose journal has nothing in it yet
    (a narrow startup race) must never claim `(0/0 agents)` -- that reads
    as a stalled run, not an about-to-start one."""
    run_dir = write_inflight_workflow(
        tmp_path,
        project_dir_name="-proj",
        session_id="sess-1",
        cwd=str(tmp_path),
        run_id="wf_a",
        started=0,
        finished=0,
    )
    (run_dir / "journal.jsonl").write_text("", encoding="utf-8")

    (record,) = discover_inflight_workflow_runs(tmp_path)

    assert record.label == "workflow in progress"


def test_malformed_or_missing_journal_degrades_to_the_generic_label(tmp_path):
    run_dir = tmp_path / "-proj" / "sess-1" / "subagents" / "workflows" / "wf_a"
    run_dir.mkdir(parents=True)
    (run_dir / "journal.jsonl").write_text("{not json", encoding="utf-8")

    (record,) = discover_inflight_workflow_runs(tmp_path)

    assert record.label == "workflow in progress"


def test_inflight_none_projects_dir_returns_empty() -> None:
    assert discover_inflight_workflow_runs(None) == []


def test_inflight_missing_projects_dir_returns_empty(tmp_path):
    assert discover_inflight_workflow_runs(tmp_path / "does-not-exist") == []


def test_two_concurrent_inflight_runs_from_one_session_both_appear(tmp_path):
    """The original reported gap, for the in-flight shape specifically: one
    session, two Workflow tool calls running at once, neither finished."""
    write_inflight_workflow(
        tmp_path, project_dir_name="-proj", session_id="sess-1", cwd=str(tmp_path), run_id="wf_one"
    )
    write_inflight_workflow(
        tmp_path, project_dir_name="-proj", session_id="sess-1", cwd=str(tmp_path), run_id="wf_two"
    )

    records = discover_inflight_workflow_runs(tmp_path)

    assert sorted(r.id for r in records) == ["workflow:wf_one", "workflow:wf_two"]


def test_an_abandoned_inflight_run_older_than_max_age_is_not_discovered(tmp_path):
    """Regression: an in-flight-*shaped* run directory whose files haven't
    moved in over a day is functionally abandoned (its process died
    without ever writing a completion summary) -- undiscovered is the
    right failure mode, not a fresh `live` tab flickering in on every
    server restart before aging back out, mirroring the completed-run
    discoverer's own `_MAX_AGE` filter."""
    run_dir = write_inflight_workflow(
        tmp_path,
        project_dir_name="-proj",
        session_id="sess-1",
        cwd=str(tmp_path),
        run_id="wf_abandoned",
        started=1,
        finished=0,
    )
    old_time = (datetime.now(UTC) - timedelta(hours=25)).timestamp()
    for f in run_dir.iterdir():
        os.utime(f, (old_time, old_time))

    assert discover_inflight_workflow_runs(tmp_path) == []


def test_inflight_workflow_activity_mtime_is_the_newest_file_in_the_run_dir(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    old = run_dir / "old.jsonl"
    new = run_dir / "new.jsonl"
    old.write_text("old", encoding="utf-8")
    new.write_text("new", encoding="utf-8")
    old_time = (datetime.now(UTC) - timedelta(hours=1)).timestamp()
    os.utime(old, (old_time, old_time))

    assert inflight_workflow_activity_mtime(run_dir) == new.stat().st_mtime


def test_inflight_workflow_activity_mtime_of_a_missing_dir_is_zero(tmp_path):
    assert inflight_workflow_activity_mtime(tmp_path / "does-not-exist") == 0.0
