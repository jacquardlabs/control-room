"""Poll-fallback attention classification for background jobs / Workflow runs.

Background tasks can't fire Claude Code's own hooks at all (design doc,
"Notifications + acknowledge": "Disk-tail polling remains the detection
path for streams that don't or can't fire hooks (background tasks...)")
-- their own state file (already read by `control_room.discovery.jobs` or
`control_room.discovery.workflows`) is the sole signal here, self-reported
by the daemon/harness rather than inferred from parsing. The two
discoverers name the same concept under two different keys -- a daemon job
writes `state`, a Workflow-tool run writes `status` -- so this classifier
reads either.
"""

from __future__ import annotations

from control_room.attention.models import AttentionState
from control_room.attention.transcripts import TailVerdict

_DONE_STATES = frozenset({"done", "completed", "succeeded"})
"""`done` (daemon jobs) and `completed` (Workflow-tool runs) are both
confirmed against real on-disk data (2026-07); `succeeded` stays a
defensive synonym, unverified against a real example of either shape."""

_FAILED_STATES = frozenset({"failed", "error", "crashed", "killed"})
"""`failed` and `killed` are confirmed against real Workflow-tool run data
(2026-07 -- a run stopped mid-flight reports `status: "killed"`, one ended
in error reports `"failed"`). `error`/`crashed` remain defensive synonyms,
unverified against a real example of either shape."""


def classify_job_record(raw: dict) -> TailVerdict:
    """Classify a job's self-reported `state`/`status` field into an attention state.

    Anything not confidently recognized -- including a state name we
    haven't verified means "blocked on a human," and including both fields
    missing entirely -- degrades to `grinding`. This is the anti-false-amber
    invariant applied to job-state classification: a job daemon or Workflow
    run reporting some new state string this detector doesn't know yet
    must never read as a false amber. A live Workflow run's own `status`
    (e.g. `"running"`) is exactly this unrecognized case today -- it isn't
    enumerated above because it doesn't need to be; it already degrades to
    the correct `grinding` without a dedicated branch.
    """
    state = raw.get("state") or raw.get("status")

    if state in _DONE_STATES:
        return TailVerdict(AttentionState.DONE)
    if state in _FAILED_STATES:
        reason = raw.get("detail") or "job reported a failure"
        return TailVerdict(AttentionState.DIED, reason=reason)
    return TailVerdict(AttentionState.GRINDING)


def is_terminal_status(raw: dict) -> bool:
    """Whether a job/Workflow-run's self-reported `state`/`status` is a
    recognized terminal one (done or failed), same vocabulary as
    `classify_job_record`.

    Used by `control_room.registry`'s own liveness check for session-
    dispatched Workflow runs specifically: their own top-level file goes
    untouched for long, normal stretches while genuinely still running
    (individual agents update their own files, not the run's), so mtime
    staleness alone would (and did, confirmed live 2026-07) falsely read an
    actively-running epic-driver as `died` within seconds. A non-terminal
    status here means "still alive" regardless of mtime; a terminal one
    still ages out through the ordinary mtime-staleness path, same as any
    finished job.
    """
    state = raw.get("state") or raw.get("status")
    return state in _DONE_STATES or state in _FAILED_STATES
