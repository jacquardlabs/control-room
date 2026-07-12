"""Build a `BoardView` for a stream that emits no board protocol.

Every field this module reads comes straight from `attention-detection`'s
and `stream-discovery`'s own output shapes (`StreamRecord`, `AttentionEvent`)
-- never a parallel, re-invented shape for "generic vitals data" (epic
pre-mortem #1's named risk). This is the whole of the "N adapters" side of
"one schema, N adapters, no renderer branches": a plain interactive session,
Workflow run, or background task becomes exactly one `Instrument`, with no
fix-budget, no blocked-on, no CAS beyond its own current state.

One enrichment reaches past the stream/event shapes: a Workflow run (either
shape -- still in flight, or already finished) carries its own dispatched
agents' results as a `verdict_trail`, the generic-adapter counterpart to
`control_room.board.protocol_adapter`'s studious-epic verdict trail. Every
other kind gets an empty trail -- there is no dispatched-agent journal for
a plain interactive session or background task.
"""

from __future__ import annotations

from pathlib import Path

from control_room.attention.models import AttentionEvent, AttentionState
from control_room.board.journal import read_subagent_results
from control_room.board.models import (
    BoardSource,
    BoardView,
    CasMessage,
    Instrument,
    VerdictTrailEntry,
)
from control_room.models import StreamKind, StreamRecord


def build_generic_board(stream: StreamRecord, event: AttentionEvent) -> BoardView:
    """One instrument, generic vitals plus -- for a Workflow run -- its own
    dispatched agents' results as a drawer."""
    instrument = Instrument(
        id=stream.id,
        label=stream.label,
        state=event.state,
        reason=event.reason,
        verdict_trail=_subagent_verdict_trail(stream),
    )
    return BoardView(
        stream_id=stream.id,
        source=BoardSource.GENERIC,
        instruments=(instrument,),
        cas=_cas_message(instrument),
    )


def _subagent_journal_dir(stream: StreamRecord) -> Path | None:
    """Where a Workflow run's own dispatched-agent journal lives, derived
    from `stream.source_path` -- `None` for any other kind (there's no such
    directory for a plain interactive session or background task).

    Two on-disk shapes, both handled (`control_room.discovery.workflows`'
    own module docstring): an in-flight run's `source_path` is already the
    run's own directory (`discover_inflight_workflow_runs` sets it that
    way); a completed run's `source_path` is its `<session>/workflows/
    <run-id>.json` summary file, one directory over from
    `<session>/subagents/workflows/<run-id>/` -- derived here, never a
    second source of truth for the run id/session.
    """
    if stream.kind is not StreamKind.WORKFLOW_RUN:
        return None
    source_path = Path(stream.source_path)
    if source_path.is_dir():
        return source_path
    run_id = source_path.stem
    session_dir = source_path.parent.parent
    return session_dir / "subagents" / "workflows" / run_id


def _subagent_verdict_trail(stream: StreamRecord) -> tuple[VerdictTrailEntry, ...]:
    run_dir = _subagent_journal_dir(stream)
    if run_dir is None:
        return ()
    return tuple(
        VerdictTrailEntry(
            step=result.agent_id[:8],
            outcome=result.summary or ("done" if result.done else "in progress"),
            sha=result.sha,
        )
        for result in read_subagent_results(run_dir)
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
