"""Golden transcript fixtures per attention state -- issue #2's acceptance criterion, verbatim.

Ties every golden fixture under `tests/fixtures/transcripts/` to the
attention state it's meant to demonstrate, in one place, so the mapping
from "acceptance criterion" to "test evidence" is unambiguous for review.

`input-blocked` and `died` aren't distinguishable from transcript content
alone (by design -- see `transcripts.py`'s module docstring on the
anti-false-amber invariant), so those two are demonstrated here by pairing
a golden transcript with the *other* signal that legitimately produces
them: a `Notification` hook payload for `input-blocked`, and a liveness
transition for `died`. This is the concrete shape of "hook-first, poll-
fallback": the transcript alone gives you `grinding` (never a guessed
amber); the confirming signal is what promotes it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from control_room.attention.hook_events import classify_hook_payload
from control_room.attention.liveness import classify_liveness_transition
from control_room.attention.models import AttentionState
from control_room.attention.transcripts import classify_transcript_tail, read_transcript_entries
from control_room.models import LiveState

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "transcripts"
NOW = datetime(2026, 7, 12, 15, 0, 0, tzinfo=UTC)


def _tail_of(name: str):
    return classify_transcript_tail(read_transcript_entries(FIXTURES_DIR / name))


def test_grinding_from_the_required_adversarial_ambiguous_tail_fixture() -> None:
    assert _tail_of("grinding__adversarial_mid_tool_call.jsonl").state == AttentionState.GRINDING


def test_review_ready_from_a_clean_finish_fixture() -> None:
    assert _tail_of("review_ready__clean_finish.jsonl").state == AttentionState.REVIEW_READY


def test_question_pending_from_a_short_clarifying_question_fixture() -> None:
    assert (
        _tail_of("question_pending__short_clarifying_question.jsonl").state
        == AttentionState.QUESTION_PENDING
    )


def test_input_blocked_is_the_same_ambiguous_transcript_promoted_by_a_notification_hook() -> None:
    """The `grinding` adversarial fixture (mid tool_use, no result yet) is
    genuinely ambiguous from the transcript alone -- exactly the scenario
    where a permission prompt would leave a stream sitting. Confirmed only
    via the Notification hook, never guessed from the transcript."""
    transcript_verdict = _tail_of("grinding__adversarial_mid_tool_call.jsonl")
    assert transcript_verdict.state == AttentionState.GRINDING  # never a guessed amber

    notification_payload = {
        "session_id": "abc123",
        "hook_event_name": "Notification",
        "notification_type": "permission_prompt",
        "message": "Permission needed for command: pytest -q",
    }
    event = classify_hook_payload(
        notification_payload, classify_transcript_tail=lambda _p: transcript_verdict, now=NOW
    )
    assert event is not None
    assert event.state == AttentionState.INPUT_BLOCKED
    assert event.reason == "Permission needed for command: pytest -q"


def test_died_is_the_same_midflight_transcript_promoted_by_a_liveness_transition() -> None:
    """A stream mid-tool-call (grinding) that then loses its process is
    `died` -- the same fixture, read through `liveness.py` instead of a
    Notification hook."""
    transcript_verdict = _tail_of("grinding__adversarial_mid_tool_call.jsonl")
    assert transcript_verdict.state == AttentionState.GRINDING

    died = classify_liveness_transition(transcript_verdict.state, LiveState.GRACE)
    assert died == AttentionState.DIED


def test_never_a_false_amber_the_long_report_ending_in_a_question() -> None:
    """The second adversarial fixture: text ends in "?" but is a
    structured, multi-paragraph report -- must not be misread as
    `question-pending` (amber)."""
    verdict = _tail_of("review_ready__adversarial_long_report_ending_in_question.jsonl")
    assert verdict.state == AttentionState.REVIEW_READY
