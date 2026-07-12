"""The wall's fleet-wide summary: every stream's attention event collapsed to counts.

`control_room.board.bucket.wall_bucket` is the one, single-owned seven-state
to N/R/M mapping (epic pre-mortem #3) -- this module never re-derives it,
only tallies its output across the whole fleet. That's the difference from
`control_room.board.models.BoardView.master_caution`: that property answers
"does *this one stream's* board need the caution lamp"; `WallSummary`
answers the same question aggregated across every stream on the wall.

One field is still a deliberately honest placeholder for a story that lands
after this one, not fabricated data:

- `aggregate_burn_usd` is `None` until `cost-vitals` (issue #7) lands a real
  per-stream cost source -- this wall renders the slot so cost-vitals only
  has to populate a number, but a `None` here is the honest "not tracked
  yet" signal DESIGN.md's "burn always with units against context" implies:
  a fabricated `$0.00` would silently claim a real, measured zero spend.

`unacknowledged_need_you` used to equal `need_you` unconditionally (no ack
mechanism existed yet); `notifications-ack` (issue #6) lands the real ack
store, so `compute_wall_summary` now takes an `is_acknowledged` predicate
and only tallies a stream as unacknowledged when that predicate says no.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from pydantic import BaseModel

from control_room.attention.models import AttentionEvent
from control_room.board.bucket import WallBucket, wall_bucket


class WallSummary(BaseModel):
    """The wall's fleet strip, verbatim from the design doc: "N grinding ·
    R review-ready · M need you · MASTER CAUTION with unacknowledged count ·
    aggregate burn."
    """

    grinding: int = 0
    review_ready: int = 0
    need_you: int = 0
    unacknowledged_need_you: int = 0
    aggregate_burn_usd: float | None = None

    @property
    def master_caution(self) -> bool:
        """Blinks for M only, never R (design doc, settled 2026-07-11)."""
        return self.unacknowledged_need_you > 0


def compute_wall_summary(
    events: Iterable[AttentionEvent],
    *,
    is_acknowledged: Callable[[AttentionEvent], bool] | None = None,
    aggregate_burn_usd: float | None = None,
) -> WallSummary:
    """Tally one AttentionEvent per stream into the wall's three live counts.

    `done` streams inflate no count (`wall_bucket` returns `None` for them),
    matching "instruments never move" -- a finished stream ages out like a
    dead one, just without the red glyph.

    `is_acknowledged` is asked only for M-bucket events (acknowledgment is a
    needs-you concept -- DESIGN.md ties MASTER CAUTION's blink and the ack
    mechanism to M alone, never to N/R). Omitting it treats every M-bucket
    stream as unacknowledged, matching this function's own behavior before
    `notifications-ack` (issue #6) existed -- callers that don't care about
    ack (most tests) don't have to thread a predicate through.
    """
    is_acknowledged = is_acknowledged or (lambda _event: False)

    grinding = review_ready = need_you = unacknowledged_need_you = 0
    for event in events:
        bucket = wall_bucket(event.state)
        if bucket is WallBucket.N:
            grinding += 1
        elif bucket is WallBucket.R:
            review_ready += 1
        elif bucket is WallBucket.M:
            need_you += 1
            if not is_acknowledged(event):
                unacknowledged_need_you += 1

    return WallSummary(
        grinding=grinding,
        review_ready=review_ready,
        need_you=need_you,
        unacknowledged_need_you=unacknowledged_need_you,
        aggregate_burn_usd=aggregate_burn_usd,
    )
