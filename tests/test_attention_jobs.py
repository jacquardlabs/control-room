"""Poll-fallback classification for background jobs and Workflow-tool runs --
the sole detection path for streams that can't fire hooks at all (design
doc). The two discoverers name the same concept under two different keys
(`state` for a daemon job, `status` for a Workflow-tool run) -- this
classifier reads either."""

from __future__ import annotations

from control_room.attention.jobs import classify_job_record
from control_room.attention.models import AttentionState


def test_done_state_is_done() -> None:
    verdict = classify_job_record({"state": "done", "detail": "PR #96 opened"})
    assert verdict.state == AttentionState.DONE
    assert verdict.reason is None


def test_failed_state_is_died_with_detail_as_reason() -> None:
    verdict = classify_job_record({"state": "failed", "detail": "dependency resolution failed"})
    assert verdict.state == AttentionState.DIED
    assert verdict.reason == "dependency resolution failed"


def test_failed_state_without_detail_gets_a_generic_reason() -> None:
    verdict = classify_job_record({"state": "failed"})
    assert verdict.state == AttentionState.DIED
    assert verdict.reason


def test_working_state_is_grinding() -> None:
    assert classify_job_record({"state": "working"}).state == AttentionState.GRINDING


def test_unrecognized_state_degrades_to_grinding_not_a_guess() -> None:
    """A job daemon reporting a brand-new state string this detector doesn't
    know yet must never read as a false amber."""
    assert (
        classify_job_record({"state": "blocked-on-something-new"}).state == AttentionState.GRINDING
    )


def test_missing_state_field_degrades_to_grinding() -> None:
    assert classify_job_record({}).state == AttentionState.GRINDING


def test_workflow_run_completed_status_is_done() -> None:
    """A Workflow-tool run reports `status`, not `state` -- confirmed
    against real `<session>/workflows/<run>.json` data, 2026-07."""
    verdict = classify_job_record({"status": "completed", "workflowName": "epic-driver"})
    assert verdict.state == AttentionState.DONE


def test_workflow_run_killed_status_is_died() -> None:
    """`killed` (a run stopped mid-flight) is confirmed against real
    Workflow-tool run data, 2026-07 -- distinct from `failed` (ended in
    error) but both read as `died`."""
    verdict = classify_job_record({"status": "killed"})
    assert verdict.state == AttentionState.DIED
    assert verdict.reason


def test_workflow_run_running_status_is_grinding() -> None:
    assert classify_job_record({"status": "running"}).state == AttentionState.GRINDING


def test_state_field_wins_over_status_when_both_present() -> None:
    """Never actually co-occurs in real data (one shape or the other, never
    both) -- pinned anyway so the precedence is a decision, not an accident
    of `or` evaluation order."""
    verdict = classify_job_record({"state": "done", "status": "running"})
    assert verdict.state == AttentionState.DONE
