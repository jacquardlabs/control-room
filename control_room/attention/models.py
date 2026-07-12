"""The attention taxonomy and the event shape every detector produces.

Discovery (`control_room.models.StreamRecord`) answers "does this stream
exist and have we lost contact with it" -- liveness bookkeeping only. This
module answers the richer question DESIGN.md's "Semantic palette" names:
what does this stream need from the human right now. The two are kept
separate deliberately (see `control_room/models.py`'s own docstring);
`control_room.attention.liveness` is the one bridge between them.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, model_validator


class AttentionState(StrEnum):
    """The seven-state attention taxonomy -- DESIGN.md's "Semantic palette," verbatim.

    String values match DESIGN.md's own vocabulary exactly, hyphens
    included, since DESIGN.md requires "one name per concept across UI,
    schema keys, notifications, and docs" -- these values ARE the schema
    keys downstream renderers will key off of.

    `parked` is listed here as part of the shared vocabulary (DESIGN.md,
    the wall's M-bucket mapping) but this package's own detectors never
    produce it: DESIGN.md ties `parked` to "a judgment verdict or exhausted
    budget (via board protocol)" -- that's board-protocol-render's
    (issue #3) concern, reading studious's adopted schema. Generic
    hook/poll detection has no equivalent generic signal to synthesize it
    from, and guessing one would risk exactly the false-amber failure mode
    this taxonomy exists to prevent.
    """

    GRINDING = "grinding"
    INPUT_BLOCKED = "input-blocked"
    QUESTION_PENDING = "question-pending"
    PARKED = "parked"
    REVIEW_READY = "review-ready"
    DIED = "died"
    DONE = "done"


AMBER_STATES = frozenset(
    {AttentionState.INPUT_BLOCKED, AttentionState.QUESTION_PENDING, AttentionState.PARKED}
)
"""DESIGN.md's amber ("needs you") classes.

`died` is red, not amber (DESIGN.md: "died -- red ... The only red"), and
`review-ready`/`done`/`grinding` are advisory or neutral -- none of the
three requires a reason the way amber states do.
"""


class AttentionSource(StrEnum):
    """Where an AttentionEvent's classification came from -- provenance, not detail.

    Distinguishing HOOK from POLL matters for the exit-gate timing claim
    (design doc: "the primary detection path ... is Claude Code's own hook
    mechanism ... not disk-tail/journal polling alone") -- a caller that
    wants to verify "was this fast" can check `source` directly rather than
    inferring it from timing alone.
    """

    HOOK = "hook"
    POLL = "poll"


class AttentionEvent(BaseModel):
    """One attention-state observation for one stream.

    DESIGN.md: "Amber classes always carry their reason text; an amber
    without a reason is a rendering bug." Enforced here as a hard
    construction-time invariant rather than a rendering-layer convention --
    a detector that tries to build an amber AttentionEvent without a reason
    fails immediately, in its own tests, not later at render time.
    """

    stream_id: str
    state: AttentionState
    reason: str | None = None
    source: AttentionSource
    at: datetime
    detail: str | None = None
    """Free-text provenance (e.g. the raw hook_event_name, or "liveness") --
    for debugging/audit only, never itself rendered as the reason."""

    @model_validator(mode="after")
    def _amber_requires_reason(self) -> AttentionEvent:
        if self.state in AMBER_STATES and not (self.reason and self.reason.strip()):
            raise ValueError(
                f"amber state {self.state!r} requires a one-clause reason (DESIGN.md invariant)"
            )
        return self
