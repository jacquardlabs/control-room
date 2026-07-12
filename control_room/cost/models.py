"""The one shape `control_room.cost.usage` produces and every caller reads.

Pydantic, matching every other shape in the stream/attention/board pipeline
(`StreamRecord`, `AttentionEvent`, `BoardView`, `WallSummary` are all
`BaseModel`) -- one modeling convention, not a plain dataclass carved out
for this one story.
"""

from __future__ import annotations

from pydantic import BaseModel


class StreamCost(BaseModel):
    """One stream's cumulative burn, computed from its transcript's own
    usage records -- never a live/estimated figure, never a threshold or
    judgment (issue #7: "vitals, not judgment").
    """

    total_usd: float | None = None
    """`None` means "nothing to report" -- no transcript, no usage records
    found in it, or every model referenced was wholly unrecognized (see
    `control_room.cost.pricing`'s "known limitation"). Never a fabricated
    `0.0`, matching `control_room.wall`'s own precedent for this exact
    distinction."""

    unpriced_models: tuple[str, ...] = ()
    """Model ids seen in the transcript that `pricing.lookup_rates`
    couldn't price at all (not even a family fallback) -- surfaced for
    debugging/audit, not rendered anywhere yet. Empty whenever every
    model referenced was priced, exactly or by family fallback."""
