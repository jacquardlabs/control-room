"""Registry tests pinned directly to the story's acceptance criteria:

"With 3 interactive sessions, 1 Workflow run, 1 background task live, all
5 appear within one poll interval (<=5s); a killed session grays within 2
intervals and ages out, never disappearing while amber; streams map to
worktrees/projects correctly; discovery is read-only by construction."
"""

from __future__ import annotations

import subprocess
import sys

from control_room.models import LiveState, StreamKind
from control_room.registry import GONE_AFTER_MISSES, GRACE_AFTER_MISSES, StreamRegistry
from tests.conftest import (
    add_linked_worktree,
    make_main_repo,
    write_job,
    write_session_file,
    write_session_workflow,
)


def _spawn_sleeper() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])


def test_five_concurrent_streams_all_appear_in_one_poll(tmp_path):
    sessions_dir = tmp_path / "sessions"
    jobs_dir = tmp_path / "jobs"
    procs = [_spawn_sleeper() for _ in range(3)]
    try:
        for i, proc in enumerate(procs):
            write_session_file(sessions_dir, pid=proc.pid, session_id=f"sid-{i}", cwd=str(tmp_path))
        write_job(jobs_dir, job_id="wf1", cwd=str(tmp_path), template="workflow")
        write_job(jobs_dir, job_id="bg1", cwd=str(tmp_path), template="bg")

        registry = StreamRegistry(sessions_dir, jobs_dir)
        records = registry.poll()

        assert len(records) == 5
        kinds = [r.kind for r in records]
        assert kinds.count(StreamKind.INTERACTIVE) == 3
        assert kinds.count(StreamKind.WORKFLOW_RUN) == 1
        assert kinds.count(StreamKind.BACKGROUND_TASK) == 1
        assert all(r.live_state == LiveState.LIVE for r in records)
    finally:
        for proc in procs:
            proc.kill()
            proc.wait()


def test_killed_session_grays_within_two_polls_then_ages_out(tmp_path):
    sessions_dir = tmp_path / "sessions"
    jobs_dir = tmp_path / "jobs"
    proc = _spawn_sleeper()
    write_session_file(sessions_dir, pid=proc.pid, session_id="sid-killed", cwd=str(tmp_path))
    registry = StreamRegistry(sessions_dir, jobs_dir)

    (record,) = registry.poll()
    assert record.live_state == LiveState.LIVE

    proc.kill()
    proc.wait()

    (record,) = registry.poll()  # miss 1
    assert record.consecutive_misses == 1
    assert record.live_state == LiveState.LIVE  # not yet graced -- one miss is a blip

    (record,) = registry.poll()  # miss 2 -- exactly GRACE_AFTER_MISSES
    assert GRACE_AFTER_MISSES == 2
    assert record.consecutive_misses == 2
    assert record.live_state == LiveState.GRACE

    # Stays present (never disappears) through misses up to the age-out edge.
    for _ in range(GONE_AFTER_MISSES - 2 - 1):
        (record,) = registry.poll()
        assert record.live_state == LiveState.GRACE

    results = registry.poll()  # final miss reaching GONE_AFTER_MISSES
    assert results == []  # aged out


def test_transient_blip_self_heals_without_graying(tmp_path):
    """A single missed poll must not gray a stream -- only sustained loss does."""
    sessions_dir = tmp_path / "sessions"
    jobs_dir = tmp_path / "jobs"
    proc = _spawn_sleeper()
    try:
        write_session_file(sessions_dir, pid=proc.pid, session_id="sid-x", cwd=str(tmp_path))
        registry = StreamRegistry(sessions_dir, jobs_dir)
        registry.poll()

        # Simulate the record vanishing from disk for one poll only (e.g. a
        # transient read race), then reappearing.
        session_path = sessions_dir / f"{proc.pid}.json"
        contents = session_path.read_text(encoding="utf-8")
        session_path.unlink()
        (record,) = registry.poll()
        assert record.consecutive_misses == 1
        assert record.live_state == LiveState.LIVE

        session_path.write_text(contents, encoding="utf-8")
        (record,) = registry.poll()
        assert record.consecutive_misses == 0
        assert record.live_state == LiveState.LIVE
    finally:
        proc.kill()
        proc.wait()


def test_protected_stream_never_ages_out_while_amber(tmp_path):
    sessions_dir = tmp_path / "sessions"
    jobs_dir = tmp_path / "jobs"
    proc = _spawn_sleeper()
    write_session_file(sessions_dir, pid=proc.pid, session_id="sid-amber", cwd=str(tmp_path))
    registry = StreamRegistry(sessions_dir, jobs_dir)
    registry.poll()

    proc.kill()
    proc.wait()

    def always_protected(_record) -> bool:
        return True

    for _ in range(GONE_AFTER_MISSES + 10):
        (record,) = registry.poll(is_protected=always_protected)

    assert record.consecutive_misses >= GONE_AFTER_MISSES
    assert record.live_state == LiveState.GRACE  # still present, still graded gray -- not gone


def test_background_job_ages_out_via_stalled_state_file(tmp_path):
    """Jobs have no pid -- staleness is inferred from state.json/timeline.jsonl mtimes."""
    jobs_dir = tmp_path / "jobs"
    sessions_dir = tmp_path / "sessions"
    write_job(jobs_dir, job_id="stall1", cwd=str(tmp_path))
    registry = StreamRegistry(sessions_dir, jobs_dir)

    (record,) = registry.poll()
    assert record.live_state == LiveState.LIVE

    for _ in range(GONE_AFTER_MISSES - 1):
        (record,) = registry.poll()
    assert record.live_state == LiveState.GRACE

    assert registry.poll() == []


def test_aged_out_job_stays_gone_when_its_state_file_is_never_deleted(tmp_path):
    """Regression: a finished job's `state.json` is never actually removed
    from disk (the CLI leaves it there) -- only its mtime stops advancing.
    Once aged out, re-discovering the same still-quiet file on a later poll
    must not read as a brand-new stream and flicker back to `live`; it must
    stay gone unless the file shows genuinely new activity."""
    jobs_dir = tmp_path / "jobs"
    sessions_dir = tmp_path / "sessions"
    write_job(jobs_dir, job_id="stall2", cwd=str(tmp_path), state="done")
    registry = StreamRegistry(sessions_dir, jobs_dir)

    for _ in range(GONE_AFTER_MISSES + 1):
        results = registry.poll()
    assert results == []  # aged out, per the test above

    # The file is untouched (no delete, no rewrite) -- confirm it stays gone
    # across many more polls, not just the one immediately after age-out.
    for _ in range(10):
        assert registry.poll() == []


def test_a_workflow_tool_run_appears_alongside_its_dispatching_session(tmp_path):
    """The story's own acceptance criterion ("1 Workflow run... appear[s]
    within one poll interval") was previously verified only through
    `~/.claude/jobs/`'s `template: "workflow"` shape (see
    test_five_concurrent_streams_all_appear_in_one_poll above) -- never
    through a real Workflow-tool call's actual on-disk shape, which lives
    under `<project>/<session>/workflows/`, not `~/.claude/jobs/` at all.
    Regression for a real reported gap: a session running Workflow tool
    calls showed neither in control-room, only the session's own tab."""
    sessions_dir = tmp_path / "sessions"
    jobs_dir = tmp_path / "jobs"
    projects_dir = tmp_path / "projects"
    write_session_workflow(
        projects_dir,
        project_dir_name="-proj",
        session_id="sess-1",
        cwd=str(tmp_path),
        run_id="wf_abc",
        workflow_name="epic-driver",
    )
    registry = StreamRegistry(sessions_dir, jobs_dir, projects_dir=projects_dir)

    (record,) = registry.poll()

    assert record.id == "workflow:wf_abc"
    assert record.kind == StreamKind.WORKFLOW_RUN
    assert record.live_state == LiveState.LIVE


def test_a_running_workflow_never_ages_out_while_its_own_file_is_quiet(tmp_path):
    """Regression, reported live during dogfooding: a session running a
    genuinely-active Workflow tool call (35 of 36 agents done, 39 minutes
    in) showed as `died` in control-room within seconds. Each dispatched
    agent updates its own file, not the run's own top-level status file --
    mtime staleness on that one file is normal here, not evidence of death.
    A `status: "running"` run must stay live indefinitely while quiet."""
    sessions_dir = tmp_path / "sessions"
    jobs_dir = tmp_path / "jobs"
    projects_dir = tmp_path / "projects"
    write_session_workflow(
        projects_dir,
        project_dir_name="-proj",
        session_id="sess-1",
        cwd=str(tmp_path),
        run_id="wf_abc",
        status="running",
    )
    registry = StreamRegistry(sessions_dir, jobs_dir, projects_dir=projects_dir)

    for _ in range(GONE_AFTER_MISSES + 5):
        (record,) = registry.poll()

    assert record.live_state == LiveState.LIVE
    assert record.consecutive_misses == 0


def test_a_completed_workflow_still_ages_out_normally(tmp_path):
    """The fix above must not blanket-protect every workflow run forever --
    once its own status turns terminal, it ages out through the ordinary
    mtime-staleness path, same as any finished job."""
    sessions_dir = tmp_path / "sessions"
    jobs_dir = tmp_path / "jobs"
    projects_dir = tmp_path / "projects"
    write_session_workflow(
        projects_dir,
        project_dir_name="-proj",
        session_id="sess-1",
        cwd=str(tmp_path),
        run_id="wf_abc",
        status="completed",
    )
    registry = StreamRegistry(sessions_dir, jobs_dir, projects_dir=projects_dir)

    for _ in range(GONE_AFTER_MISSES + 1):
        results = registry.poll()

    assert results == []


def test_workflow_runs_group_next_to_their_dispatching_session(tmp_path):
    """Regression, reported live during dogfooding: a session dispatching
    two Workflow tool calls read as three unrelated, scattered tabs -- pure
    id-alphabetical sort (`interactive:` < `job:` < `workflow:`) grouped
    every interactive session together and every workflow run together,
    never a session next to the runs it dispatched. A second, unrelated
    session (whose own id sorts between the two, proving this isn't just
    incidental alphabetical luck) must not land between them."""
    sessions_dir = tmp_path / "sessions"
    jobs_dir = tmp_path / "jobs"
    projects_dir = tmp_path / "projects"
    proc = _spawn_sleeper()
    other_proc = _spawn_sleeper()
    try:
        write_session_file(sessions_dir, pid=proc.pid, session_id="sess-1", cwd=str(tmp_path))
        write_session_file(sessions_dir, pid=other_proc.pid, session_id="sess-2", cwd=str(tmp_path))
        write_session_workflow(
            projects_dir,
            project_dir_name="-proj",
            session_id="sess-1",
            cwd=str(tmp_path),
            run_id="wf_alpha",
        )
        write_session_workflow(
            projects_dir,
            project_dir_name="-proj",
            session_id="sess-1",
            cwd=str(tmp_path),
            run_id="wf_beta",
        )
        registry = StreamRegistry(sessions_dir, jobs_dir, projects_dir=projects_dir)

        records = registry.poll()

        assert [r.id for r in records] == [
            "interactive:sess-1",
            "workflow:wf_alpha",
            "workflow:wf_beta",
            "interactive:sess-2",
        ]
        assert records[1].parent_stream_id == "interactive:sess-1"
        assert records[2].parent_stream_id == "interactive:sess-1"
        assert records[3].parent_stream_id is None
    finally:
        proc.kill()
        proc.wait()
        other_proc.kill()
        other_proc.wait()


def test_streams_map_to_worktrees_and_projects_correctly(tmp_path):
    main_root = make_main_repo(tmp_path / "control-room", branch="main")
    worktree = add_linked_worktree(
        main_root,
        tmp_path / "control-room" / ".studious" / "worktrees" / "t1" / "stream-discovery",
        name="stream-discovery",
        branch="epic/t1--stream-discovery",
    )
    sessions_dir = tmp_path / "sessions"
    jobs_dir = tmp_path / "jobs"
    proc = _spawn_sleeper()
    try:
        write_session_file(sessions_dir, pid=proc.pid, session_id="sid-wt", cwd=str(worktree))
        registry = StreamRegistry(sessions_dir, jobs_dir)

        (record,) = registry.poll()

        assert record.project_name == "control-room"
        assert record.project_root == str(main_root)
        assert record.worktree_name == "stream-discovery"
        assert record.git_branch == "epic/t1--stream-discovery"
    finally:
        proc.kill()
        proc.wait()


def test_discovery_is_read_only(tmp_path):
    """Polling must never write, create, or delete anything under the watched dirs."""
    sessions_dir = tmp_path / "sessions"
    jobs_dir = tmp_path / "jobs"
    write_session_file(sessions_dir, pid=999999, session_id="sid-ro", cwd=str(tmp_path))
    write_job(jobs_dir, job_id="ro1", cwd=str(tmp_path))

    def snapshot() -> dict[str, tuple[float, int]]:
        watched = tmp_path / "sessions", tmp_path / "jobs"
        return {
            str(p): (p.stat().st_mtime, p.stat().st_size)
            for root in watched
            for p in root.rglob("*")
            if p.is_file()
        }

    before = snapshot()
    registry = StreamRegistry(sessions_dir, jobs_dir)
    for _ in range(3):
        registry.poll()
    after = snapshot()

    assert before == after
