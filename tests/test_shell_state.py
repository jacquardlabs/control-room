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

from control_room.attention.models import AttentionSource, AttentionState
from control_room.board.ledger import SUPPORTED_SCHEMA_VERSION
from control_room.models import LiveState
from control_room.registry import GONE_AFTER_MISSES, GRACE_AFTER_MISSES
from control_room.shell.state import FleetState
from tests.conftest import add_linked_worktree, make_main_repo, write_job, write_session_file


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


def _write_parked_epic(main_root, *, slug: str, story_slug: str, label: str, reason: str) -> None:
    epics_dir = main_root / ".studious" / "epics"
    epics_dir.mkdir(parents=True, exist_ok=True)
    (epics_dir / f"{slug}.json").write_text(
        json.dumps(
            {
                "schemaVersion": SUPPORTED_SCHEMA_VERSION,
                "slug": slug,
                "stories": {story_slug: {"status": "parked", "title": label, "reason": reason}},
            }
        ),
        encoding="utf-8",
    )


def _build_background_epic(tmp_path, *, reason: str = "NEEDS DISCUSSION"):
    """A background-task stream on an `epic/t1` worktree branch, whose ledger
    already shows one parked story -- the exact "park in a background epic"
    shape issue #6's acceptance criteria names. The job's own `state.json`
    stays `"working"` throughout: a background epic driver idling on a human
    decision is still a live process, not a finished/failed one, so the raw,
    generic detector alone would never move this stream off `grinding`."""
    main_root = make_main_repo(tmp_path / "proj")
    worktree = add_linked_worktree(main_root, tmp_path / "proj-wt", name="wt", branch="epic/t1")
    _write_parked_epic(
        main_root, slug="t1", story_slug="notifications-ack", label="auth-refresh", reason=reason
    )
    jobs_dir = tmp_path / "jobs"
    write_job(jobs_dir, job_id="epic-driver", cwd=str(worktree), state="working")
    return jobs_dir


def test_a_parked_story_in_a_background_epic_elevates_onto_the_wall(tmp_path):
    """Issue #6's acceptance criterion, verbatim: "A park in a background
    epic notifies within one poll interval." The generic detector alone
    (`control_room.attention.jobs.classify_job_record`) can never produce
    `parked` -- `control_room.board.elevate.elevate_event` is the bridge
    that makes this stream's own top-level event, and therefore the wall
    tally and MASTER CAUTION, reflect it."""
    jobs_dir = _build_background_epic(tmp_path)
    state = FleetState(tmp_path / "sessions", jobs_dir, tmp_path / "events")

    snapshot = state.poll()

    assert len(snapshot.streams) == 1
    item = snapshot.streams[0]
    assert item.event.state == AttentionState.PARKED
    assert item.event.source == AttentionSource.BOARD
    assert "auth-refresh" in item.event.reason
    assert "NEEDS DISCUSSION" in item.event.reason
    assert snapshot.wall.need_you == 1
    assert snapshot.wall.unacknowledged_need_you == 1
    assert snapshot.wall.master_caution is True


def test_acknowledging_the_parked_stream_stops_the_blink_and_survives_a_restart(tmp_path):
    jobs_dir = _build_background_epic(tmp_path)
    sessions_dir, events_dir = tmp_path / "sessions", tmp_path / "events"
    state = FleetState(sessions_dir, jobs_dir, events_dir)

    first = state.poll()
    (item,) = first.streams
    state.acknowledge(item.stream.id, state=item.event.state, reason=item.event.reason)

    acked = state.poll()
    assert acked.wall.unacknowledged_need_you == 0
    assert acked.wall.master_caution is False
    assert acked.streams[0].acknowledged is True
    assert 'aria-pressed="true"' in acked.streams[0].board_html
    assert 'class="master-caution blink"' not in acked.streams[0].board_html

    # "Ack state survives server restart" -- a brand-new FleetState pointed
    # at the same disk (the same simulated restart every other test in this
    # file uses) must still see the acknowledged identity.
    restarted = FleetState(sessions_dir, jobs_dir, events_dir)
    after_restart = restarted.poll()
    assert after_restart.wall.unacknowledged_need_you == 0
    assert after_restart.wall.master_caution is False


def test_notify_fires_once_for_a_new_park_and_never_again_unacknowledged(tmp_path):
    jobs_dir = _build_background_epic(tmp_path)
    calls = []
    state = FleetState(
        tmp_path / "sessions",
        jobs_dir,
        tmp_path / "events",
        notify=lambda t, b: calls.append((t, b)),
    )

    for _ in range(4):
        state.poll()

    assert len(calls) == 1
    title, body = calls[0]
    assert title == "control-room"
    assert "auth-refresh" in body
    assert "parked" in body


def test_process_loss_after_an_elevated_park_is_normal_cleanup_not_died(tmp_path):
    """`control_room.attention.liveness`'s own `_MIDFLIGHT_STATES` docstring
    already named this case before anything in this codebase could produce
    a `parked` event at all: losing the process after `parked` is normal
    cleanup, never `died` -- verified here against a *board-elevated* park
    specifically, since elevation is what first makes that scenario
    reachable for a background epic."""
    jobs_dir = _build_background_epic(tmp_path)
    state = FleetState(tmp_path / "sessions", jobs_dir, tmp_path / "events")

    first = state.poll()
    assert first.streams[0].event.state == AttentionState.PARKED

    # Stop touching the job's own files -- standing in for the driver
    # process going away while still parked, waiting on the human.
    last = None
    for _ in range(GRACE_AFTER_MISSES + 3):
        last = state.poll()

    assert len(last.streams) == 1  # never disappeared -- protected while M-bucket
    assert last.streams[0].stream.live_state == LiveState.GRACE
    assert last.streams[0].event.state == AttentionState.PARKED  # not DIED
