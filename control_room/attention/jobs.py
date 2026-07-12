"""Poll-fallback attention classification for background jobs / Workflow runs.

Background tasks can't fire Claude Code's own hooks at all (design doc,
"Notifications + acknowledge": "Disk-tail polling remains the detection
path for streams that don't or can't fire hooks (background tasks...)")
-- their own `state.json` (already read by `control_room.discovery.jobs`)
is the sole signal here, self-reported by the daemon rather than inferred
from parsing.
"""

from __future__ import annotations

from control_room.attention.models import AttentionState
from control_room.attention.transcripts import TailVerdict

_DONE_STATES = frozenset({"done", "completed", "succeeded"})
"""Only "done" has been observed in real `~/.claude/jobs/*/state.json` data
(2026-07, while building this); "completed"/"succeeded" are defensive
synonyms, unverified against a real example."""

_FAILED_STATES = frozenset({"failed", "error", "crashed"})
"""Unverified against real data -- no failing job was available to inspect
while building this. Included defensively, same posture as
`control_room.discovery.jobs.classify_job_kind`'s own documented
limitation: named explicitly rather than silently assumed.
"""


def classify_job_record(raw: dict) -> TailVerdict:
    """Classify a job's self-reported `state` field into an attention state.

    Anything not confidently recognized -- including any state name we
    haven't verified means "blocked on a human," and including a missing
    `state` field entirely -- degrades to `grinding`. This is the
    anti-false-amber invariant applied to job-state classification: a job
    daemon that starts reporting some new state string this detector
    doesn't know yet must never read as a false amber.
    """
    state = raw.get("state")

    if state in _DONE_STATES:
        return TailVerdict(AttentionState.DONE)
    if state in _FAILED_STATES:
        reason = raw.get("detail") or "job reported a failure"
        return TailVerdict(AttentionState.DIED, reason=reason)
    return TailVerdict(AttentionState.GRINDING)
