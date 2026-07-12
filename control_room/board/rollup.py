"""Fold a dispatched stream's own board view into its dispatcher's pane.

`control_room.models.StreamRecord.parent_stream_id` names the relationship;
this module is what merges the *board content* once
`control_room.shell.state.FleetState` has decided a child renders inside its
parent's pane rather than its own tab -- reported live (2026-07): a session
dispatching two Workflow tool calls still read as three separate, unrelated
things even once the tab strip merely grouped them side by side.
`BoardView.instruments` already holds more than one row for a protocol board
(one per story, all under one epic's own tab); this reuses exactly that
shape, one row per child stream, rather than inventing a second, nested
board concept.
"""

from __future__ import annotations

from collections.abc import Sequence

from control_room.board.models import BoardView


def merge_child_boards(parent: BoardView, children: Sequence[BoardView]) -> BoardView:
    """`parent`'s own instruments/CAS lines, followed by each child's, in the
    order given -- DESIGN.md's "instruments never move" extended to a merged
    pane: the parent's own row is always first, children after, never
    re-sorted by state here or anywhere downstream (`render_board` walks
    `instruments` in exactly this order).

    Every other `BoardView` field (`stream_id`, `source`,
    `degraded_from_protocol`, ...) stays the parent's own -- the merged pane
    is still keyed to the parent's own tab/ack/notification identity, and a
    child's own board is always a plain generic-adapter view today (a
    Workflow run is never itself protocol-eligible), so there is no
    degraded-protocol flag of a child's to surface here.
    """
    if not children:
        return parent
    instruments = parent.instruments
    cas = parent.cas
    for child in children:
        instruments += child.instruments
        cas += child.cas
    return parent.model_copy(update={"instruments": instruments, "cas": cas})
