"""Build a `BoardView` from studious's gate-ledger epic protocol.

The one place studious's own story vocabulary (`pending`/`landed`/`parked`/
`dropped` -- `workflows/epic-driver.js`'s own status checks, verbatim; there
is no distinct "in progress" story status in gate-ledger's real vocabulary,
only these four plus whatever a future version adds) meets control-room's
generic seven-state taxonomy -- DESIGN.md: "no studious-isms in shared
vocabulary," so the translation happens once, at this boundary, never
downstream (CLAUDE.md: "Fix data at the boundary, not at the point of
use"). An unrecognized status string (including any future addition this
adapter hasn't been updated for) degrades to `grinding`, never a guessed
amber -- the same anti-false-amber invariant every detector in this
codebase honors (`control_room.attention`'s own docstrings, verbatim).

Board scope is the whole epic, one instrument per story: this is what
"a live /work-through epic renders parks/reasons/fix-pips" (the story's
acceptance criteria) means -- one tab per running epic, not one tab per
story worktree.
"""

from __future__ import annotations

from control_room.attention.models import AMBER_STATES, AttentionState
from control_room.board.bucket import WallBucket, wall_bucket
from control_room.board.ledger import EpicLedger, StoryLedger
from control_room.board.models import BoardSource, BoardView, CasMessage, FixBudget, Instrument

_STATUS_TO_STATE: dict[str, AttentionState] = {
    "landed": AttentionState.DONE,
    "parked": AttentionState.PARKED,
    # Pending covers both "queued behind a dep" and "a worker is actively
    # building it right now" -- gate-ledger's own ledger doesn't distinguish
    # the two at the story-status level (only `pending`/`landed`/`parked`/
    # `dropped` exist), so both read as the same silent, unremarkable
    # default: nothing is needed from the human yet.
    "pending": AttentionState.GRINDING,
    # A dropped story is deliberately abandoned, not mid-flight and not
    # needing a human decision right now -- closest fit in a strictly
    # seven-state generic vocabulary is `done`: it inflates no wall count
    # and ages out like a finished stream (DESIGN.md's "done" bullet).
    "dropped": AttentionState.DONE,
}


def _state_for_status(status: str) -> AttentionState:
    """Unrecognized status text degrades to `grinding` -- never a guessed amber."""
    return _STATUS_TO_STATE.get(status, AttentionState.GRINDING)


def _blocked_on(story: StoryLedger, stories: dict[str, StoryLedger]) -> tuple[str, ...]:
    """Names of direct deps not yet `landed` -- design-history.md's "blocked
    instruments naming their blocker." Only a `pending` story ever carries
    this: `landed`/`parked`/`dropped` are all past the DAG-scheduling
    question entirely (the epic driver only ever schedules a `pending`
    story once every dependency has landed, so a still-`pending` story is
    the only one that can be "blocked on" anything)."""
    if story.status != "pending":
        return ()
    return tuple(dep for dep in story.deps if stories.get(dep, StoryLedger()).status != "landed")


def _fix_budget(story: StoryLedger) -> FixBudget | None:
    """The worst (most fix-and-retry-consumed) gate's counter -- one dial per
    instrument, not one per gate. `None` when no gate has ever needed a retry."""
    if not story.retries:
        return None
    return FixBudget(used=max(story.retries.values()))


def _resolution_command(epic_slug: str, story_slug: str, story: StoryLedger) -> str | None:
    """The un-park incantation `work-through.md`'s "Skips, amendments, and
    un-parking" section documents verbatim, pre-filled with what's known and
    a placeholder for what only the human can supply (the fix itself)."""
    if story.status != "parked":
        return None
    gate_hint = (
        story.reason.split(":", 1)[0].strip() if story.reason and ":" in story.reason else "<gate>"
    )
    return (
        f'gate-ledger epic-story-set --epic "{epic_slug}" --slug "{story_slug}" '
        f'--status pending --reason "resolved: <one clause>" --reset-retry {gate_hint}'
    )


def _instrument(
    epic_slug: str, story_slug: str, story: StoryLedger, epic: EpicLedger
) -> Instrument:
    state = _state_for_status(story.status)
    reason = story.reason if state in AMBER_STATES else None
    return Instrument(
        id=story_slug,
        label=story.title or story_slug,
        state=state,
        reason=reason,
        blocked_on=_blocked_on(story, epic.stories),
        fix_budget=_fix_budget(story),
        resolution_command=_resolution_command(epic_slug, story_slug, story),
    )


def _cas_messages(instruments: tuple[Instrument, ...]) -> tuple[CasMessage, ...]:
    relevant = [i for i in instruments if wall_bucket(i.state) in (WallBucket.M, WallBucket.R)]

    def severity_rank(instrument: Instrument) -> int:
        return 0 if wall_bucket(instrument.state) is WallBucket.M else 1

    ordered = sorted(relevant, key=severity_rank)
    return tuple(
        CasMessage(
            instrument_id=i.id,
            state=i.state,
            text=f"{i.label} -- {i.state.value}" + (f": {i.reason}" if i.reason else ""),
        )
        for i in ordered
    )


def build_protocol_board(epic: EpicLedger, *, stream_id: str) -> BoardView:
    """Translate one epic ledger into the one board schema, whole-epic scope."""
    instruments = tuple(
        _instrument(epic.slug, story_slug, story, epic)
        for story_slug, story in epic.stories.items()
    )
    return BoardView(
        stream_id=stream_id,
        source=BoardSource.PROTOCOL,
        instruments=instruments,
        cas=_cas_messages(instruments),
    )
