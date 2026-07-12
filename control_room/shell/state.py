"""Assemble one fleet snapshot: registry poll -> per-stream attention -> board -> wall.

Recomputed from scratch on every `FleetState.poll()` call -- nothing here is
cached across ticks or persisted across a restart. `StreamRegistry` already
keeps its own liveness bookkeeping in memory only (its docstring: every
`poll()` re-scans disk from scratch); `FleetState` adds exactly one more
in-memory-only fact, each stream's last-resolved `AttentionState`, needed
for two things `resolve_attention` and the registry both require:

- `resolve_attention`'s `previous_state` argument (to detect a mid-flight
  `died` transition -- see `control_room.attention.liveness`).
- the registry's `is_protected` predicate (a stream in the wall's M bucket
  must never age out while amber, even if its disk artifact vanishes).

Losing that dict on restart is indistinguishable from every stream
reappearing for the first time -- exactly `StreamRegistry.poll()`'s own
already-accepted restart posture (a stream defaults to `LiveState.LIVE`,
zero misses, the first time it's seen). A stream's previous state
defaults to `grinding` the first time it's observed, matching the
anti-false-amber invariant: unknown history degrades to the neutral
default, never to a remembered amber that isn't actually evidenced yet.

**Terminal states (`died`/`done`) are sticky across polls, once observed.**
This is a real composition bug caught while wiring the poll loop, not a
speculative guard: `resolve_attention`'s poll-fallback has no disk signal
that means "died" (a dead process leaves no transcript tail that reads as
anything but ambiguous-therefore-`grinding`, and a cleaned-up job
`state.json` reads as an empty dict, also `grinding`) -- so a stream
correctly classified `died` (or `done`, whose `state.json` is equally
liable to be removed after completion) would silently flip back to
`grinding` on the very next tick if it were re-derived instead of carried
forward. `resolve_attention`'s own docstring frames the liveness override
as authoritative ("always wins"); this module is the first caller that
polls the same stream more than once, so it's the first place this needed
to be enforced.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from control_room.attention.detector import resolve_attention
from control_room.attention.models import AttentionEvent, AttentionState
from control_room.attention.store import EventLogStore
from control_room.board.bucket import WallBucket, wall_bucket
from control_room.board.dispatch import resolve_board_view
from control_room.board.render import render_board
from control_room.cost.usage import compute_stream_cost
from control_room.models import StreamRecord
from control_room.registry import StreamRegistry
from control_room.wall import WallSummary, compute_wall_summary

_TERMINAL_STATES = frozenset({AttentionState.DIED, AttentionState.DONE})
"""Once true, never re-derived -- see this module's docstring."""


class StreamSnapshot(BaseModel):
    """One tab's worth of current-truth: the stream, its attention event, and
    its already-rendered board fragment (so the server never re-renders the
    same tick's HTML twice -- once here, once for the wire payload).

    Pydantic, not a plain dataclass, to match the rest of the
    stream/attention schema (`StreamRecord`, `AttentionEvent`, `WallSummary`
    are all `BaseModel`) -- one modeling convention for one pipeline, not
    two. `frozen=True` keeps the "one snapshot, one tick, never mutated"
    invariant the dataclass version had."""

    model_config = ConfigDict(frozen=True)

    stream: StreamRecord
    event: AttentionEvent
    board_html: str
    burn_usd: float | None = None
    """This stream's cumulative cost so far (`cost-vitals`, issue #7) --
    `None` when its transcript can't be resolved yet, never a fabricated
    `0.0` (same "no file, no guess" posture as everything else this
    snapshot carries)."""


class FleetSnapshot(BaseModel):
    """The whole screen, once, for one poll tick."""

    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    wall: WallSummary
    streams: tuple[StreamSnapshot, ...]


class FleetState:
    """Owns the two in-memory-only facts described above. Not thread-safe --
    call from one loop only (mirrors `StreamRegistry`'s own contract).

    `control_room.shell.server.FleetHTTPServer` owns exactly one instance
    for the lifetime of the server process and advances it from exactly one
    background thread; every `/events` connection (a first load, a second
    tab, or the browser's own silent reconnect after a transient drop)
    reads the same cached, already-resolved snapshot rather than calling
    `poll()` itself. That's deliberate, not incidental: this module's own
    docstring above explains why terminal states must be carried forward
    across polls of the *same* state -- an `EventSource` reconnect is a new
    HTTP connection, not a new server, so it must not see a new
    `FleetState` either, or the same "silently un-dies a stream" bug
    recurs one layer up. A real process restart still resets everything,
    because that *is* a new `FleetHTTPServer` and therefore a new
    `FleetState` -- restart losing only in-memory bookkeeping, never
    disk-observable truth, is the acceptance criterion this story asks for.
    """

    def __init__(
        self,
        sessions_dir: Path,
        jobs_dir: Path,
        events_dir: Path,
        *,
        projects_dir: Path | None = None,
    ) -> None:
        self._registry = StreamRegistry(sessions_dir, jobs_dir)
        self._event_store = EventLogStore(events_dir)
        self._previous_event: dict[str, AttentionEvent] = {}
        self._projects_dir = projects_dir

    def poll(self, *, now: datetime | None = None) -> FleetSnapshot:
        now = now or datetime.now(UTC)
        streams = self._registry.poll(is_protected=self._is_protected, now=now)

        snapshots = []
        events = []
        burns: list[float] = []
        for stream in streams:
            event = self._resolve(stream, now=now)
            self._previous_event[stream.id] = event
            events.append(event)

            board_view = resolve_board_view(stream, event)
            burn_usd = self._burn(stream)
            if burn_usd is not None:
                burns.append(burn_usd)
            snapshots.append(
                StreamSnapshot(
                    stream=stream,
                    event=event,
                    board_html=render_board(board_view),
                    burn_usd=burn_usd,
                )
            )

        # A stream the registry dropped this tick (aged out, not protected)
        # carries no fresh event -- drop its stale remembered state too, so
        # a same-id stream appearing later starts from `grinding` again
        # rather than inheriting a long-gone stream's last state.
        live_ids = {s.id for s in streams}
        for stale_id in [sid for sid in self._previous_event if sid not in live_ids]:
            del self._previous_event[stale_id]

        return FleetSnapshot(
            generated_at=now,
            wall=compute_wall_summary(events, aggregate_burn_usd=sum(burns) if burns else None),
            streams=tuple(snapshots),
        )

    def _resolve(self, stream: StreamRecord, *, now: datetime) -> AttentionEvent:
        """One stream's current AttentionEvent -- carried forward unchanged
        once terminal (see module docstring), otherwise handed to
        `resolve_attention` as usual."""
        previous = self._previous_event.get(stream.id)
        if previous is not None and previous.state in _TERMINAL_STATES:
            return previous.model_copy(update={"at": now})

        return resolve_attention(
            stream,
            latest_hook_event=self._event_store.latest(stream.id),
            previous_state=previous.state if previous is not None else AttentionState.GRINDING,
            now=now,
        )

    def _burn(self, stream: StreamRecord) -> float | None:
        """This stream's cumulative cost so far, or `None` if its
        transcript(s) can't be resolved -- `compute_stream_cost` already
        commits to "no file, no guess"; this is just where it's plugged
        into the poll loop. Known limitation (named in `cost.usage`'s own
        docstring): recomputed from scratch every tick, not incremental."""
        return compute_stream_cost(stream, projects_dir=self._projects_dir).total_usd

    def _is_protected(self, record: StreamRecord) -> bool:
        """Never age a stream out of the registry while it's in the wall's M
        bucket (design doc: "never disappearing while amber"), keyed off the
        *previous* tick's resolved state -- this tick's fresh state isn't
        known yet when the registry decides survivorship."""
        previous = self._previous_event.get(record.id)
        return previous is not None and wall_bucket(previous.state) is WallBucket.M
