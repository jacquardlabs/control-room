"""The one decision: does this tick's attention event fire an OS notification.

DESIGN.md, verbatim: "One per state *change*; body names the stream, the
state, and the one-clause reason; acknowledged streams stay silent until a
new event." `should_notify` is that rule, plus the debounce/hysteresis this
design doc's own open question named as unresolved ("a detector flickering
near a heuristic threshold ... could fire a burst of near-duplicate
notifications for what is really one continuous state") and the epic
pre-mortem flagged as a real risk (#3: "notification debounce ships without a
real threshold and a flickering detector produces the exact
notification-fatigue the design warned about").

Scoped to the M (need-you) bucket only -- `input-blocked`, `question-pending`,
`parked`, `died` -- matching DESIGN.md's "Blink is reserved for
unacknowledged needs-you" and PRODUCT.md's both critical journeys, which tie
acknowledge and the one interrupt-worthy notification to needs-you moments
specifically, never to `review-ready`/`done`/`grinding` transitions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from control_room.attention.ack import AckRecord
from control_room.attention.models import AttentionEvent
from control_room.board.bucket import WallBucket

NOTIFY_HYSTERESIS = timedelta(seconds=20)
"""How long after firing a notification a *different*-looking identity on
the same stream is still treated as noise from the same episode, not a new
one worth a second OS interruption.

This is the debounce the design doc left as an open, un-thresholded
question. 20s is chosen relative to `fleet-shell`'s own default 3s poll
interval (`control_room.shell.server.DEFAULT_POLL_INTERVAL`) -- generous
enough to smooth over several consecutive ticks of a detector oscillating
near a classification boundary (the design doc's own named example:
"grinding -> amber -> grinding -> amber within a short window"), short
enough that a genuinely separate problem arising a minute later still gets
its own prompt notification rather than being silently swallowed. Exact-
identity dedup (below) has no such window -- the *same* state+reason never
re-notifies at all while unacknowledged, no matter how much time passes;
this window only covers the case where the detector's momentary noise
produces a slightly different-looking identity for what is, to the owner,
one continuous situation.
"""


@dataclass(frozen=True)
class NotifyDecision:
    """One tick's notify outcome for one stream: whether to fire, and the
    `AckRecord` to persist afterward either way."""

    should_fire: bool
    record: AckRecord


def evaluate(
    event: AttentionEvent, bucket: WallBucket | None, record: AckRecord, *, now: datetime
) -> NotifyDecision:
    """Decide whether `event` fires a notification, and what `record` becomes.

    Leaving the M bucket entirely ends the episode: the record resets to
    fully empty rather than carrying stale identity/timestamp bookkeeping
    forward, so a *later* re-entry into M -- even with identical wording --
    is judged as new, not "already handled." (Acknowledge state also resets
    here deliberately: once a stream is no longer in the M bucket, there is
    nothing left to acknowledge, and DESIGN.md's ack/blink pairing is
    M-bucket-scoped throughout.)
    """
    if bucket is not WallBucket.M:
        return NotifyDecision(should_fire=False, record=AckRecord())

    if not _should_fire(event, record, now=now):
        return NotifyDecision(should_fire=False, record=record)

    updated = record.model_copy(
        update={
            "last_notified_state": event.state,
            "last_notified_reason": event.reason,
            "last_notified_at": now,
        }
    )
    return NotifyDecision(should_fire=True, record=updated)


def _should_fire(event: AttentionEvent, record: AckRecord, *, now: datetime) -> bool:
    if record.is_acknowledged(event):
        return False  # DESIGN.md: "silenced by acknowledge, never repeated without a new event"

    if (record.last_notified_state, record.last_notified_reason) == (event.state, event.reason):
        return False  # issue #6 acceptance: never notifies twice for the same unacked state

    # Debounce: a differently-worded re-read moments after the last
    # notification reads as noise from the same episode, not a new one.
    return record.last_notified_at is None or (now - record.last_notified_at) > NOTIFY_HYSTERESIS
