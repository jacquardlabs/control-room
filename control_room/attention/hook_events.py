"""Hook-first attention detection: classify one Claude Code hook payload synchronously.

Design doc ("Notifications + acknowledge"): "the primary detection path for
a state change is Claude Code's own hook mechanism, firing synchronously at
the same moment the harness's own notification would -- not disk-tail/
journal polling alone, which is bounded by a multi-second poll interval."
This module is that synchronous path: given one hook JSON payload (as
Claude Code delivers it on the registered hook command's stdin -- see
`control_room.attention.entrypoint`), return the AttentionEvent it implies,
or `None` if the payload isn't attention-relevant.

Hook schema facts below were verified against code.claude.com/docs/en/hooks
while building this (2026-07-12), not assumed from training data alone
(CLAUDE.md: "check official docs ... don't rely on training data alone").
Two facts were independently reproduced across separate targeted fetches
and are load-bearing here: (1) `agent_id` is a common input field present
on hook payloads "only when the hook fires inside a subagent call"; (2)
`Notification`'s matcher filters on a notification-type value with example
values including `permission_prompt` and `idle_prompt`. The exact JSON key
carrying that notification-type value could not be independently confirmed
(the page's dedicated `Notification` section wasn't retrievable in full),
so `_classify_notification` below hedges with a text-content fallback
rather than trusting one guessed key name exclusively.

Subagent suppression (issue #2's acceptance criterion, verbatim: "hook-first
detection verified against a Task-dispatched subagent path, not just the
interactive session"): any hook payload carrying a truthy `agent_id` fired
from *inside* a Task-dispatched subagent call, never from the top-level
session. A subagent finishing or calling a tool must never flip the PARENT
stream's own attention state -- the parent orchestrator is still working
while its dispatched subagent runs. Concretely, this means the same
`hook_event_name` (e.g. `Stop`, `PreToolUse`) must classify differently
depending on whether `agent_id` is present -- see this module's tests for
the paired top-level/subagent fixtures.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from control_room.attention.models import AttentionEvent, AttentionSource, AttentionState
from control_room.attention.transcripts import TailVerdict

_RESUME_EVENTS = frozenset({"PreToolUse", "PostToolUse", "UserPromptSubmit"})
"""Hook events that mean "the top-level stream is actively working right now."

Firing after a prior amber/review-ready state is exactly the "state
changed back" transition DESIGN.md's notification rule cares about (an OS
notification fires only on a *change*) -- so a `PreToolUse` resuming after
`question-pending` must re-emit `grinding`, not stay silent and leave the
wall showing a stale amber.
"""

_PERMISSION_KEYWORDS = ("permission", "approve", "approval")
"""Conservative fallback text match for a permission-prompt `Notification`,
used when a `notification_type`-shaped field is absent or doesn't match the
expected `permission_prompt` value -- hedges the field-name uncertainty
documented in this module's own docstring above.
"""

TranscriptTailClassifier = Callable[[str], TailVerdict]


def classify_hook_payload(
    payload: dict,
    *,
    classify_transcript_tail: TranscriptTailClassifier,
    now: datetime | None = None,
) -> AttentionEvent | None:
    """Classify one raw hook JSON payload into an AttentionEvent, or None.

    `None` means "not attention-relevant": an unrecognized event, a
    subagent-scoped event, or a `Notification` whose type this detector
    doesn't confidently map to an attention state. Never raises: a
    malformed payload (missing `session_id`/`hook_event_name`) degrades to
    `None`, the same "never fail the whole read over one bad payload"
    posture stream-discovery's own parsers use.

    `classify_transcript_tail` is injected (rather than reading the
    transcript file directly here) purely for testability -- the real
    entrypoint wires it to `transcripts.read_transcript_entries` +
    `transcripts.classify_transcript_tail`.
    """
    now = now or datetime.now(UTC)
    stream_id = payload.get("session_id")
    event_name = payload.get("hook_event_name")
    if not stream_id or not event_name:
        return None

    if payload.get("agent_id"):
        return None  # subagent-scoped -- never the parent stream's own state (module docstring)

    if event_name in _RESUME_EVENTS:
        return AttentionEvent(
            stream_id=stream_id,
            state=AttentionState.GRINDING,
            source=AttentionSource.HOOK,
            at=now,
            detail=event_name,
        )

    if event_name == "Notification":
        return _classify_notification(payload, stream_id=stream_id, now=now)

    if event_name == "Stop":
        return _classify_stop(
            payload, stream_id=stream_id, now=now, classify_transcript_tail=classify_transcript_tail
        )

    # SubagentStop, PreCompact, SessionStart/End, and anything this
    # detector doesn't recognize yet: not attention-relevant. Forward-
    # compatible by construction -- a new hook event Claude Code adds later
    # is silently ignored rather than crashing the hook script.
    return None


def _classify_stop(
    payload: dict,
    *,
    stream_id: str,
    now: datetime,
    classify_transcript_tail: TranscriptTailClassifier,
) -> AttentionEvent | None:
    transcript_path = payload.get("transcript_path")
    if not transcript_path:
        return None
    verdict = classify_transcript_tail(transcript_path)
    return AttentionEvent(
        stream_id=stream_id,
        state=verdict.state,
        reason=verdict.reason,
        source=AttentionSource.HOOK,
        at=now,
        detail="Stop",
    )


def _classify_notification(
    payload: dict, *, stream_id: str, now: datetime
) -> AttentionEvent | None:
    notification_type = payload.get("notification_type")
    message = (payload.get("message") or "").strip()
    is_permission = notification_type == "permission_prompt" or any(
        keyword in message.lower() for keyword in _PERMISSION_KEYWORDS
    )
    if not is_permission:
        # idle/auth/other notification types: not confidently mapped to an
        # attention state here. Not a gap in practice -- the same "turn
        # ended" moment a Stop-worthy idle notification implies is also
        # covered by the Stop hook itself, which resolves it through the
        # tail-classifier instead of a guess from a notification string.
        return None
    return AttentionEvent(
        stream_id=stream_id,
        state=AttentionState.INPUT_BLOCKED,
        reason=message or "permission needed",
        source=AttentionSource.HOOK,
        at=now,
        detail="Notification",
    )
