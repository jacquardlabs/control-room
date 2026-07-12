"""The seven-state attention taxonomy to N/R/M wall-bucket mapping -- owned once.

Epic pre-mortem #3 ("duplicated wall-bucket mapping") names this exact risk:
`fleet-shell` and `board-protocol-render` both touch wall/tab rendering, and
without a single owner the mapping could exist twice and drift. This module
is that single owner -- `fleet-shell` (issue #4) imports `wall_bucket` from
here rather than re-deriving it; nothing about the mapping is duplicated in
this codebase.

Values and grouping are DESIGN.md's "Semantic palette" and the T1 design
doc's wall bullet, verbatim:

- **N (grinding)** -- `grinding` only.
- **R (review-ready)** -- `review-ready` only, kept apart from `grinding` so
  a finished-and-waiting stream never looks like a still-working one.
- **M (need you)** -- `input-blocked` + `question-pending` + `parked` +
  `died`. `died` counts here (a dead stream demands attention as much as a
  blocked one) but the design doc reserves the red glyph for it alone --
  that per-stream rendering detail lives in `control_room.board.render`,
  not in this mapping.
- **Neither** -- `done`. It inflates no count and ages out like a dead
  stream, just without the red glyph (design doc, verbatim).
"""

from __future__ import annotations

from enum import StrEnum

from control_room.attention.models import AttentionState

_M_STATES = frozenset(
    {
        AttentionState.INPUT_BLOCKED,
        AttentionState.QUESTION_PENDING,
        AttentionState.PARKED,
        AttentionState.DIED,
    }
)


class WallBucket(StrEnum):
    """The wall's three live counts. `done` streams map to no bucket at all."""

    N = "N"
    R = "R"
    M = "M"


def wall_bucket(state: AttentionState) -> WallBucket | None:
    """The one function: seven attention states in, one of three buckets (or
    None for `done`) out. Never duplicate this mapping elsewhere -- import it."""
    if state is AttentionState.GRINDING:
        return WallBucket.N
    if state is AttentionState.REVIEW_READY:
        return WallBucket.R
    if state in _M_STATES:
        return WallBucket.M
    return None
