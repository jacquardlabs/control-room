"""The wall's fleet-wide summary: every stream's attention event collapsed to counts.

`control_room.board.bucket.wall_bucket` is the one, single-owned seven-state
to N/R/M mapping (epic pre-mortem #3) -- this module never re-derives it,
only tallies its output across the whole fleet. That's the difference from
`control_room.board.models.BoardView.master_caution`: that property answers
"does *this one stream's* board need the caution lamp"; `WallSummary`
answers the same question aggregated across every stream on the wall.

Two fields are deliberately honest placeholders for stories that land after
this one, not fabricated data:

- `unacknowledged_need_you` equals `need_you` until `notifications-ack`
  (issue #6) lands a real ack store -- every M-bucket stream is
  unacknowledged by construction until an acknowledge mechanism exists at
  all, so the equality is correct today, not a stand-in for a missing
  computation.
- `aggregate_burn_usd` is `None` until `cost-vitals` (issue #7) lands a real
  per-stream cost source -- this wall renders the slot so cost-vitals only
  has to populate a number, but a `None` here is the honest "not tracked
  yet" signal DESIGN.md's "burn always with units against context" implies:
  a fabricated `$0.00` would silently claim a real, measured zero spend.
"""

from __future__ import annotations

from collections.abc import Iterable

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
    events: Iterable[AttentionEvent], *, aggregate_burn_usd: float | None = None
) -> WallSummary:
    """Tally one AttentionEvent per stream into the wall's three live counts.

    `done` streams inflate no count (`wall_bucket` returns `None` for them),
    matching "instruments never move" -- a finished stream ages out like a
    dead one, just without the red glyph.
    """
    grinding = review_ready = need_you = 0
    for event in events:
        bucket = wall_bucket(event.state)
        if bucket is WallBucket.N:
            grinding += 1
        elif bucket is WallBucket.R:
            review_ready += 1
        elif bucket is WallBucket.M:
            need_you += 1

    return WallSummary(
        grinding=grinding,
        review_ready=review_ready,
        need_you=need_you,
        unacknowledged_need_you=need_you,
        aggregate_burn_usd=aggregate_burn_usd,
    )
