from __future__ import annotations

import time

from control_room.discovery.jobs import discover_jobs, job_activity_mtime
from control_room.models import StreamKind
from tests.conftest import add_linked_worktree, make_main_repo, write_job


def test_discovers_one_record_per_job_dir(tmp_path):
    jobs_dir = tmp_path / "jobs"
    write_job(jobs_dir, job_id="7871e584", cwd=str(tmp_path), name="fix-workthrough")

    records = discover_jobs(jobs_dir)

    assert len(records) == 1
    record = records[0]
    assert record.id == "job:7871e584"
    assert record.kind == StreamKind.BACKGROUND_TASK
    assert record.label == "fix-workthrough"
    assert record.pid is None


def test_bg_template_classifies_as_background_task(tmp_path):
    jobs_dir = tmp_path / "jobs"
    write_job(jobs_dir, job_id="a1", cwd=str(tmp_path), template="bg")

    (record,) = discover_jobs(jobs_dir)

    assert record.kind == StreamKind.BACKGROUND_TASK


def test_workflow_template_classifies_as_workflow_run(tmp_path):
    jobs_dir = tmp_path / "jobs"
    write_job(jobs_dir, job_id="a2", cwd=str(tmp_path), template="workflow")

    (record,) = discover_jobs(jobs_dir)

    assert record.kind == StreamKind.WORKFLOW_RUN


def test_non_directory_entries_alongside_jobs_are_skipped(tmp_path):
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    (jobs_dir / "pins.json").write_text("{}", encoding="utf-8")
    (jobs_dir / ".draft-abcd").write_text("x", encoding="utf-8")
    write_job(jobs_dir, job_id="real", cwd=str(tmp_path))

    records = discover_jobs(jobs_dir)

    assert [r.id for r in records] == ["job:real"]


def test_missing_state_json_is_skipped_not_raised(tmp_path):
    jobs_dir = tmp_path / "jobs"
    empty_job = jobs_dir / "half-written"
    empty_job.mkdir(parents=True)

    assert discover_jobs(jobs_dir) == []


def test_maps_to_worktree_via_cwd(tmp_path):
    main_root = make_main_repo(tmp_path / "proj")
    worktree = add_linked_worktree(main_root, tmp_path / "proj-wt", name="wt", branch="feature")
    jobs_dir = tmp_path / "jobs"
    write_job(jobs_dir, job_id="j1", cwd=str(worktree))

    (record,) = discover_jobs(jobs_dir)

    assert record.project_name == "proj"
    assert record.worktree_name == "wt"
    assert record.git_branch == "feature"


def test_job_activity_mtime_reflects_latest_touch(tmp_path):
    jobs_dir = tmp_path / "jobs"
    state_path = write_job(jobs_dir, job_id="j1", cwd=str(tmp_path))

    before = job_activity_mtime(state_path)
    time.sleep(0.01)
    state_path.write_text(state_path.read_text(encoding="utf-8"), encoding="utf-8")
    after = job_activity_mtime(state_path)

    assert after >= before
