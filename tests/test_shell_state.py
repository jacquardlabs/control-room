"""`FleetState.poll()`: registry -> attention -> board -> wall, in one call.

Focus is the integration seam fleet-shell owns, not re-testing each story's
own logic (registry/attention/board already have their own suites) -- plus
the two invariants this story's acceptance criteria name directly: a killed
session grays then reports `died` (never disappearing while amber), and a
fresh `FleetState` pointed at the same disk reconstructs the same picture a
"kill and restart the server" would produce.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

from control_room.attention.models import AttentionState
from control_room.registry import GONE_AFTER_MISSES, GRACE_AFTER_MISSES
from control_room.shell.state import FleetState
from tests.conftest import write_job, write_session_file


def _spawn_sleeper() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])


def test_empty_disk_yields_empty_snapshot_and_zeroed_wall(tmp_path):
    state = FleetState(tmp_path / "sessions", tmp_path / "jobs", tmp_path / "events")
    snapshot = state.poll()
    assert snapshot.streams == ()
    assert snapshot.wall.grinding == 0
    assert snapshot.wall.master_caution is False


def test_grinding_session_produces_one_snapshot_with_rendered_board(tmp_path):
    sessions_dir = tmp_path / "sessions"
    proc = _spawn_sleeper()
    try:
        write_session_file(sessions_dir, pid=proc.pid, session_id="s1", cwd=str(tmp_path))
        state = FleetState(sessions_dir, tmp_path / "jobs", tmp_path / "events")
        snapshot = state.poll()

        assert len(snapshot.streams) == 1
        (item,) = snapshot.streams
        assert item.event.state == AttentionState.GRINDING
        assert "board" in item.board_html
        assert snapshot.wall.grinding == 1
    finally:
        proc.kill()
        proc.wait()


def test_poll_populates_per_stream_burn_and_wall_aggregate(tmp_path):
    sessions_dir = tmp_path / "sessions"
    projects_dir = tmp_path / "projects"
    proc = _spawn_sleeper()
    try:
        write_session_file(sessions_dir, pid=proc.pid, session_id="s1", cwd=str(tmp_path))

        project_dir = projects_dir / str(tmp_path.resolve()).replace("/", "-")
        project_dir.mkdir(parents=True)
        (project_dir / "s1.jsonl").write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "requestId": "req-1",
                    "message": {
                        "id": "m1",
                        "model": "claude-opus-4-5-20251101",
                        "usage": {"input_tokens": 1_000_000},
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

        state = FleetState(
            sessions_dir, tmp_path / "jobs", tmp_path / "events", projects_dir=projects_dir
        )
        snapshot = state.poll()

        (item,) = snapshot.streams
        assert item.burn_usd == 5.0  # 1M input tokens @ $5/Mtok
        assert snapshot.wall.aggregate_burn_usd == 5.0
    finally:
        proc.kill()
        proc.wait()


def test_poll_leaves_wall_aggregate_burn_none_when_no_stream_prices(tmp_path):
    jobs_dir = tmp_path / "jobs"
    write_job(jobs_dir, job_id="j1", cwd=str(tmp_path), state="working")
    state = FleetState(tmp_path / "sessions", jobs_dir, tmp_path / "events")
    snapshot = state.poll()

    (item,) = snapshot.streams
    assert item.burn_usd is None
    assert snapshot.wall.aggregate_burn_usd is None


def test_done_job_inflates_no_wall_count(tmp_path):
    jobs_dir = tmp_path / "jobs"
    write_job(jobs_dir, job_id="j1", cwd=str(tmp_path), state="done")
    state = FleetState(tmp_path / "sessions", jobs_dir, tmp_path / "events")
    snapshot = state.poll()

    assert len(snapshot.streams) == 1
    assert snapshot.streams[0].event.state == AttentionState.DONE
    assert snapshot.wall.grinding == 0
    assert snapshot.wall.review_ready == 0
    assert snapshot.wall.need_you == 0


def test_killed_grinding_session_reports_died_and_never_disappears_while_amber(tmp_path):
    sessions_dir = tmp_path / "sessions"
    proc = _spawn_sleeper()
    write_session_file(sessions_dir, pid=proc.pid, session_id="s-killed", cwd=str(tmp_path))
    state = FleetState(sessions_dir, tmp_path / "jobs", tmp_path / "events")

    (first,) = state.poll().streams
    assert first.event.state == AttentionState.GRINDING

    proc.kill()
    proc.wait()

    last_snapshot = None
    for _ in range(GRACE_AFTER_MISSES + 1):
        last_snapshot = state.poll()

    assert last_snapshot is not None
    assert len(last_snapshot.streams) == 1  # never disappeared while amber (M-bucket: died)
    assert last_snapshot.streams[0].event.state == AttentionState.DIED
    assert last_snapshot.wall.need_you == 1
    assert last_snapshot.wall.master_caution is True

    # Regression: a stream classified `died` must stay `died` on further
    # polls, not flap back to `grinding` -- poll-fallback has no disk signal
    # for "died" at all (an unresolvable transcript reads as ambiguous, which
    # degrades to `grinding`), so re-deriving instead of carrying the
    # terminal state forward would silently un-die it one tick later.
    for _ in range(3):
        again = state.poll()
        assert again.streams[0].event.state == AttentionState.DIED


def test_done_job_state_survives_state_json_cleanup(tmp_path):
    """A job daemon that deletes its own `state.json` after finishing (a
    real, common cleanup pattern) must not cause the job to flip from `done`
    back to `grinding` -- `classify_job_record` reads a missing/unreadable
    file as an empty dict, which is indistinguishable from "no signal", and
    degrades to `grinding` on its own. `FleetState` must not let that
    silently overwrite an already-observed terminal `done`."""
    jobs_dir = tmp_path / "jobs"
    job_state_path = write_job(jobs_dir, job_id="j1", cwd=str(tmp_path), state="done")
    state = FleetState(tmp_path / "sessions", jobs_dir, tmp_path / "events")

    (first,) = state.poll().streams
    assert first.event.state == AttentionState.DONE

    shutil.rmtree(job_state_path.parent)

    (second,) = state.poll().streams
    assert second.event.state == AttentionState.DONE


def test_restart_reconstructs_the_same_picture_from_disk(tmp_path):
    """A fresh `FleetState` (simulating a server restart) pointed at the same
    disk truth as a long-running one produces the same current attention
    state for a stream that has been grinding all along -- restart loses
    only in-memory bookkeeping, never disk-observable truth."""
    sessions_dir = tmp_path / "sessions"
    proc = _spawn_sleeper()
    try:
        write_session_file(sessions_dir, pid=proc.pid, session_id="s1", cwd=str(tmp_path))

        long_running = FleetState(sessions_dir, tmp_path / "jobs", tmp_path / "events")
        long_running.poll()
        long_running.poll()

        restarted = FleetState(sessions_dir, tmp_path / "jobs", tmp_path / "events")
        snapshot = restarted.poll()

        assert len(snapshot.streams) == 1
        assert snapshot.streams[0].event.state == AttentionState.GRINDING
    finally:
        proc.kill()
        proc.wait()


def test_previous_state_bookkeeping_does_not_grow_unboundedly(tmp_path):
    """A stream that ages out entirely (not protected -- it was never amber)
    must not leave its state behind in `FleetState`'s own memory forever."""
    jobs_dir = tmp_path / "jobs"
    job_state_path = write_job(jobs_dir, job_id="j1", cwd=str(tmp_path), state="done")
    state = FleetState(tmp_path / "sessions", jobs_dir, tmp_path / "events")
    state.poll()
    assert "job:j1" in state._previous_event

    shutil.rmtree(job_state_path.parent)

    for _ in range(GONE_AFTER_MISSES + 1):
        state.poll()

    assert "job:j1" not in state._previous_event
