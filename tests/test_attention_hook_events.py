"""Hook-first attention classification, including the Task-dispatched subagent path.

Issue #2's acceptance criterion, verbatim: "hook-first detection verified
against a Task-dispatched subagent path (not just the interactive
session)." The tests below are built as PAIRS -- the same
`hook_event_name`, once with `agent_id` absent (top-level session) and once
present (fired from inside a Task-dispatched subagent) -- asserting the two
must classify differently. This is the concrete, code-level meaning of
"verified against a subagent path": a subagent finishing or calling a tool
must never flip the PARENT stream's own attention state.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from control_room.attention.hook_events import classify_hook_payload
from control_room.attention.models import AttentionSource, AttentionState
from control_room.attention.transcripts import TailVerdict

NOW = datetime(2026, 7, 12, 13, 45, 0, tzinfo=UTC)


def _tail_stub(state: AttentionState = AttentionState.REVIEW_READY, reason: str | None = None):
    def _classify(_transcript_path: str) -> TailVerdict:
        return TailVerdict(state, reason)

    return _classify


# --- The Task-dispatched subagent path (the acceptance criterion, verbatim) ---


@pytest.mark.parametrize("event_name", ["PreToolUse", "PostToolUse", "Stop"])
def test_subagent_scoped_event_never_flips_the_parent_stream(event_name: str) -> None:
    """Same event, `agent_id` present -- fired from inside a Task-dispatched
    subagent. Must NOT surface as the parent stream's own state change."""
    payload = {
        "session_id": "abc123",
        "hook_event_name": event_name,
        "agent_id": "subagent-1",
        "agent_type": "Explore",
        "transcript_path": "/tmp/whatever.jsonl",
    }
    assert classify_hook_payload(payload, classify_transcript_tail=_tail_stub(), now=NOW) is None


@pytest.mark.parametrize(
    ("event_name", "expected_state"),
    [("PreToolUse", AttentionState.GRINDING), ("PostToolUse", AttentionState.GRINDING)],
)
def test_top_level_event_without_agent_id_does_flip_the_stream(
    event_name: str, expected_state: AttentionState
) -> None:
    """Same event names as above, `agent_id` absent -- the top-level
    interactive session itself. Must classify normally."""
    payload = {"session_id": "abc123", "hook_event_name": event_name}
    event = classify_hook_payload(payload, classify_transcript_tail=_tail_stub(), now=NOW)
    assert event is not None
    assert event.state == expected_state
    assert event.stream_id == "abc123"
    assert event.source == AttentionSource.HOOK


def test_top_level_stop_delegates_to_the_transcript_tail_classifier() -> None:
    payload = {"session_id": "abc123", "hook_event_name": "Stop", "transcript_path": "/tmp/t.jsonl"}
    event = classify_hook_payload(
        payload, classify_transcript_tail=_tail_stub(AttentionState.REVIEW_READY), now=NOW
    )
    assert event is not None
    assert event.state == AttentionState.REVIEW_READY
    assert event.source == AttentionSource.HOOK
    assert event.detail == "Stop"


def test_subagent_stop_is_suppressed_via_agent_id_even_without_a_dedicated_branch() -> None:
    """SubagentStop always carries agent_id by construction -- the agent_id
    check alone is sufficient, with no special-casing of the event name."""
    payload = {
        "session_id": "abc123",
        "hook_event_name": "SubagentStop",
        "agent_id": "subagent-1",
        "transcript_path": "/tmp/whatever.jsonl",
    }
    assert classify_hook_payload(payload, classify_transcript_tail=_tail_stub(), now=NOW) is None


# --- Notification -> input-blocked, with its one-clause reason ---


def test_permission_notification_is_input_blocked_with_message_as_reason() -> None:
    payload = {
        "session_id": "abc123",
        "hook_event_name": "Notification",
        "notification_type": "permission_prompt",
        "message": "Permission needed for command: npm test",
    }
    event = classify_hook_payload(payload, classify_transcript_tail=_tail_stub(), now=NOW)
    assert event is not None
    assert event.state == AttentionState.INPUT_BLOCKED
    assert event.reason == "Permission needed for command: npm test"


def test_permission_notification_recognized_by_message_text_when_type_field_absent() -> None:
    """Hedge against notification-type field-name uncertainty (module
    docstring): a message that reads as a permission ask is still caught
    even without a recognized `notification_type` value."""
    payload = {
        "session_id": "abc123",
        "hook_event_name": "Notification",
        "message": "Claude needs your permission to use Bash",
    }
    event = classify_hook_payload(payload, classify_transcript_tail=_tail_stub(), now=NOW)
    assert event is not None
    assert event.state == AttentionState.INPUT_BLOCKED


def test_idle_notification_is_not_confidently_classified_here() -> None:
    """Not a gap: the same "turn ended" moment is also covered by Stop,
    which resolves it through the tail-classifier instead of guessing from
    a notification string."""
    payload = {
        "session_id": "abc123",
        "hook_event_name": "Notification",
        "notification_type": "idle_prompt",
        "message": "Claude has been idle for 5 minutes",
    }
    assert classify_hook_payload(payload, classify_transcript_tail=_tail_stub(), now=NOW) is None


# --- Malformed / unrecognized input never raises ---


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"session_id": "abc123"},
        {"hook_event_name": "Stop"},
        {"session_id": "abc123", "hook_event_name": "PreCompact"},
        {"session_id": "abc123", "hook_event_name": "SomeFutureHookEvent"},
    ],
)
def test_malformed_or_unrecognized_payloads_degrade_to_none(payload: dict) -> None:
    assert classify_hook_payload(payload, classify_transcript_tail=_tail_stub(), now=NOW) is None


def test_stop_without_transcript_path_degrades_to_none() -> None:
    payload = {"session_id": "abc123", "hook_event_name": "Stop"}
    assert classify_hook_payload(payload, classify_transcript_tail=_tail_stub(), now=NOW) is None
