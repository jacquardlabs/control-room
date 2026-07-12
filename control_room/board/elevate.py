"""Elevate a board's own instrument-level `parked` verdict onto the stream's
top-level `AttentionEvent` -- the bridge `notifications-ack` needs to make a
background epic's park visible at the wall/notification level.

The gap this closes: `control_room.attention.models.AttentionState`'s own
docstring is explicit that generic hook/poll detection "never produces
[`parked`]" -- board-protocol data is the only source for it
(`control_room.board.protocol_adapter._STATUS_TO_STATE`). But
`control_room.wall.compute_wall_summary` and this story's own ack/notify
bookkeeping both operate on each stream's *single* top-level `AttentionEvent`
(`control_room.shell.state.FleetState`'s `events` list), not on
`BoardView.instruments`. Without this bridge, a parked story inside a
background epic (a `background_task`/`workflow_run` stream whose own
`state.json` still reads "working," since the driver process is merely
idle-and-waiting, not exited) would never move that stream's own event off
`grinding` -- invisible to the fleet-wide M count, MASTER CAUTION, and every
notification this story adds, until the owner happened to open that one tab.
That is exactly the "discovers it needed me an hour ago" failure PRODUCT.md
names as the reason control-room exists, so leaving it un-bridged would
defeat the whole point of a background epic having a wall presence at all.

`control_room.attention.liveness.classify_liveness_transition`'s own
`_MIDFLIGHT_STATES` docstring already lists `parked` among the states where
losing the process afterward is "just normal cleanup, not `died`" -- written
before anything in this codebase could actually produce a `parked`
`AttentionEvent`. That's why elevation is the intended completion of the
design, not a new fork in it.
"""

from __future__ import annotations

from control_room.attention.models import AttentionEvent, AttentionSource, AttentionState
from control_room.board.bucket import WallBucket, wall_bucket
from control_room.board.models import BoardView, Instrument

_ELEVATION_ELIGIBLE = frozenset({AttentionState.GRINDING, AttentionState.REVIEW_READY})
"""The only raw states elevation ever overrides -- both mean "the generic
detector has nothing amber to report," which is exactly the blind spot
board-protocol parks fall into, never a claim of certainty elevation should
compete with.

Deliberately excludes every M-bucket state (a hook/poll-confirmed
`input-blocked`/`question-pending`, or a liveness-confirmed `died`, always
wins -- `control_room.attention.detector.resolve_attention`'s own precedence
already treats a liveness `died` as authoritative, and a live hook signal is
fresher and more specific than a ledger snapshot) and excludes `done` (a
terminal, sticky state -- `control_room.shell.state.FleetState`'s own
"terminal states are sticky" invariant means a stream that has already
finished must never be resurrected as `parked` just because its last-read
ledger snapshot hadn't caught up yet).
"""


def elevate_event(event: AttentionEvent, view: BoardView) -> AttentionEvent:
    """Return `event`, or a `parked` event adopted from `view`'s own
    instruments when `event` is a placeholder the generic detector produced
    only for lack of anything better to say.

    Picks the first M-bucket instrument in `view.instruments`' own
    (never-reordered, DESIGN.md "instruments never move") definition order --
    stable and deterministic, not a severity re-sort, matching how
    `control_room.board.protocol_adapter` already orders instruments story by
    story rather than by state.
    """
    if event.state not in _ELEVATION_ELIGIBLE:
        return event

    instrument = _first_needs_you_instrument(view.instruments)
    if instrument is None:
        return event

    reason = f"{instrument.label}: {instrument.reason}" if instrument.reason else instrument.label
    return AttentionEvent(
        stream_id=event.stream_id,
        state=instrument.state,
        reason=reason,
        source=AttentionSource.BOARD,
        at=event.at,
        detail="board-protocol",
    )


def _first_needs_you_instrument(instruments: tuple[Instrument, ...]) -> Instrument | None:
    return next((i for i in instruments if wall_bucket(i.state) is WallBucket.M), None)
