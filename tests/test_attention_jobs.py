"""Poll-fallback classification for background jobs -- the sole detection
path for streams that can't fire hooks at all (design doc)."""

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
