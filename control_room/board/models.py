"""The one board schema every adapter builds and the one renderer consumes.

`control_room.attention.models.AttentionEvent`/`control_room.models.StreamRecord`
are the shapes this module builds *from* -- never re-invented (epic
pre-mortem #1, "renderer/detector interface drift"). `BoardView` is the
richer, per-tab shape this story adds on top of them: fix-budget wedges,
blocked-on naming, CAS messages, the drawer's resolution command -- the "v2
review items" DESIGN.md and the design-history.md Flight Deck v2 pass named.

Two adapters build a `BoardView` (`control_room.board.protocol_adapter`,
`control_room.board.generic_adapter`); `control_room.board.render` renders
either one through the same code, branching only on field values, never on
`BoardView.source`.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, model_validator

from control_room.attention.models import AMBER_STATES, AttentionState
from control_room.board.bucket import WallBucket, wall_bucket


class BoardSource(StrEnum):
    """Which adapter built a `BoardView` -- provenance for callers/tests, never
    a rendering branch (`control_room.board.render` never inspects this)."""

    PROTOCOL = "protocol"
    GENERIC = "generic"


class FixBudget(BaseModel):
    """One instrument's fix-and-retry budget -- the dial's wedges.

    Mirrors `work-through.md`'s driver rule verbatim: "bump-retry <gate>;
    park once the recorded counter exceeds 2" -- so `cap` defaults to 2
    (two fix-and-retry cycles tolerated before a judgment park), and
    `used` is the current gate's retry counter for the instrument's story.
    """

    used: int
    cap: int = 2

    @property
    def wedges(self) -> tuple[bool, ...]:
        """One slot per `cap`, `True` where a retry has consumed it.

        design-history.md: "fix-budget wedges on the dial itself" -- this is
        the data the renderer paints them from, never re-derived at render
        time.
        """
        return tuple(slot < self.used for slot in range(self.cap))

    @property
    def exhausted(self) -> bool:
        return self.used > self.cap


class VerdictTrailEntry(BaseModel):
    """One round of an instrument's own build/audit/fix/retry history --
    DESIGN.md's "verdict trail," read via
    `control_room.board.ledger.load_work_history` and rendered inside an
    on-demand drawer, never ambient (DESIGN.md: "opened on demand")."""

    step: str
    outcome: str
    sha: str | None = None
    at: str | None = None


class Instrument(BaseModel):
    """One row on the board -- one story (protocol) or one stream (generic).

    `id` is the stable identity DESIGN.md's "instruments never move" pins
    ordering to: `control_room.board.render` sorts/keeps instruments by
    `id`'s definition order, never by `state`, so a park never reshuffles
    the board.
    """

    id: str
    label: str
    state: AttentionState
    reason: str | None = None
    blocked_on: tuple[str, ...] = ()
    """Names of instruments this one is blocked on -- design-history.md's
    "blocked instruments naming their blocker." Empty when nothing blocks
    it (including for every generic-adapter instrument, which never has
    dependency data)."""
    fix_budget: FixBudget | None = None
    """`None` for generic-vitals instruments -- there is no fix-and-retry
    concept without the protocol."""
    resolution_command: str | None = None
    """A copy-pasteable command for the drawer (design doc's user journey,
    step 3), e.g. the `gate-ledger epic-story-set ... --status pending`
    un-park incantation `work-through.md` documents. `None` when there is
    nothing actionable to hand the drawer."""
    verdict_trail: tuple[VerdictTrailEntry, ...] = ()
    """This instrument's own build/audit/fix/retry history, oldest first --
    the drawer's other piece of content alongside `resolution_command`.
    Empty for a generic-adapter instrument (there is no gate-ledger
    work-log without the protocol) and for a protocol instrument with
    nothing recorded yet (e.g. a story still `pending`, never dispatched)."""

    @property
    def fix_lamp_on(self) -> bool:
        """Latched, not current-state: once a fix cycle has fired, the FIX
        lamp stays lit even if the instrument later lands cleanly.

        design-history.md: "latched FIX lamps carrying history without a
        timeline" -- this is what "latched" means operationally: it is a
        function of `fix_budget.used`, never of `state`.
        """
        return self.fix_budget is not None and self.fix_budget.used > 0

    @model_validator(mode="after")
    def _amber_requires_reason(self) -> Instrument:
        """Same construction-time invariant as `AttentionEvent`'s (reused, not
        re-derived): DESIGN.md's "an amber without a reason is a rendering
        bug" applies to a board instrument exactly as it does to a raw
        attention event -- a buggy adapter fails in its own tests, not later
        at render time."""
        if self.state in AMBER_STATES and not (self.reason and self.reason.strip()):
            raise ValueError(
                f"amber state {self.state!r} requires a one-clause reason (DESIGN.md invariant)"
            )
        return self


class CasMessage(BaseModel):
    """One line in the Crew Alerting System list -- the aria-live announcement feed."""

    instrument_id: str
    state: AttentionState
    text: str


class BoardView(BaseModel):
    """The one schema. Every adapter builds this; the one renderer only reads it."""

    stream_id: str
    source: BoardSource
    instruments: tuple[Instrument, ...]
    cas: tuple[CasMessage, ...] = ()
    degraded_from_protocol: bool = False
    """Set by `control_room.board.dispatch` when a protocol-eligible stream's
    ledger couldn't be read at a supported version -- the view itself is a
    fully-valid generic view; this flag is only a loud, visible breadcrumb
    (design doc: "protocol version mismatch degrades to generic vitals
    loudly")."""
    degraded_reason: str | None = None

    @property
    def master_caution(self) -> bool:
        """True while any instrument sits in the wall's M (need-you) bucket.

        Uses `control_room.board.bucket.wall_bucket` -- the one function
        DESIGN.md/the epic pre-mortem require; never a second, parallel
        classification here.
        """
        return any(wall_bucket(i.state) is WallBucket.M for i in self.instruments)
