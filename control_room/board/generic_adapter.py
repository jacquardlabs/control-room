"""Build a `BoardView` for a stream that emits no board protocol.

Every field this module reads comes straight from `attention-detection`'s
and `stream-discovery`'s own output shapes (`StreamRecord`, `AttentionEvent`)
-- never a parallel, re-invented shape for "generic vitals data" (epic
pre-mortem #1's named risk). This is the whole of the "N adapters" side of
"one schema, N adapters, no renderer branches": a plain interactive session,
Workflow run, or background task becomes exactly one `Instrument`, with no
fix-budget, no blocked-on, no CAS beyond its own current state.
"""

from __future__ import annotations

from control_room.attention.models import AttentionEvent, AttentionState
from control_room.board.models import BoardSource, BoardView, CasMessage, Instrument
from control_room.models import StreamRecord


def build_generic_board(stream: StreamRecord, event: AttentionEvent) -> BoardView:
    """One instrument, generic vitals only -- no protocol enrichment."""
    instrument = Instrument(
        id=stream.id,
        label=stream.label,
        state=event.state,
        reason=event.reason,
    )
    return BoardView(
        stream_id=stream.id,
        source=BoardSource.GENERIC,
        instruments=(instrument,),
        cas=_cas_message(instrument),
    )


def _cas_message(instrument: Instrument) -> tuple[CasMessage, ...]:
    """A single stream only ever needs one CAS line, and only while it's
    something other than the silent `grinding` default."""
    if instrument.state is AttentionState.GRINDING:
        return ()
    text = instrument.label + " -- " + instrument.state.value
    if instrument.reason:
        text += f": {instrument.reason}"
    return (CasMessage(instrument_id=instrument.id, state=instrument.state, text=text),)
