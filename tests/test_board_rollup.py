"""`merge_child_boards`: folding a dispatched stream's own board view into
its dispatcher's pane -- the content half of the "one pane, not one tab per
dispatched Workflow run" fix (`control_room.shell.state.FleetState` is the
other half, deciding *which* streams get folded).
"""

from __future__ import annotations

from control_room.attention.models import AttentionState
from control_room.board.models import BoardSource, BoardView, CasMessage, Instrument
from control_room.board.rollup import merge_child_boards


def _instrument(id: str, state: AttentionState = AttentionState.GRINDING) -> Instrument:
    return Instrument(id=id, label=id, state=state)


def _view(stream_id: str, *instruments: Instrument, cas: tuple[CasMessage, ...] = ()) -> BoardView:
    return BoardView(
        stream_id=stream_id, source=BoardSource.GENERIC, instruments=instruments, cas=cas
    )


def test_no_children_returns_the_parent_view_unchanged() -> None:
    parent = _view("interactive:sess-1", _instrument("interactive:sess-1"))
    assert merge_child_boards(parent, []) is parent


def test_children_instruments_append_after_the_parents_own_in_order() -> None:
    """DESIGN.md's "instruments never move" extended to a merged pane: the
    parent's own row is always first, children after, in the order given."""
    parent = _view("interactive:sess-1", _instrument("interactive:sess-1"))
    child_a = _view("workflow:wf_a", _instrument("workflow:wf_a"))
    child_b = _view("workflow:wf_b", _instrument("workflow:wf_b"))

    merged = merge_child_boards(parent, [child_a, child_b])

    assert [i.id for i in merged.instruments] == [
        "interactive:sess-1",
        "workflow:wf_a",
        "workflow:wf_b",
    ]


def test_merged_view_keeps_the_parents_own_identity() -> None:
    """The merged pane is still keyed to the parent's own tab/ack identity
    -- `stream_id`/`source` come from the parent, never a child."""
    parent = _view("interactive:sess-1", _instrument("interactive:sess-1"))
    child = _view("workflow:wf_a", _instrument("workflow:wf_a"))

    merged = merge_child_boards(parent, [child])

    assert merged.stream_id == "interactive:sess-1"
    assert merged.source == BoardSource.GENERIC


def test_a_died_childs_instrument_makes_the_merged_view_report_master_caution() -> None:
    """`BoardView.master_caution` is `any(instrument in M bucket)` -- merging
    a dead child's instrument into the parent's own list is what lets a
    session's pane visibly escalate for a dispatched Workflow run's death,
    with no change needed to `master_caution` itself."""
    parent = _view("interactive:sess-1", _instrument("interactive:sess-1"))
    dead_child = _view("workflow:wf_a", _instrument("workflow:wf_a", AttentionState.DIED))

    merged = merge_child_boards(parent, [dead_child])

    assert merged.master_caution is True


def test_cas_lines_concatenate_parent_first_then_children() -> None:
    parent_cas = (
        CasMessage(instrument_id="interactive:sess-1", state=AttentionState.GRINDING, text="p"),
    )
    child_cas = (CasMessage(instrument_id="workflow:wf_a", state=AttentionState.DIED, text="c"),)
    parent = _view("interactive:sess-1", _instrument("interactive:sess-1"), cas=parent_cas)
    child = _view("workflow:wf_a", _instrument("workflow:wf_a", AttentionState.DIED), cas=child_cas)

    merged = merge_child_boards(parent, [child])

    assert [m.text for m in merged.cas] == ["p", "c"]
