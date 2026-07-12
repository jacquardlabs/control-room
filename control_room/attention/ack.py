"""Persisted per-stream acknowledge + notify-dedup bookkeeping.

Two concerns share one disk-backed record per stream, because both compare
against the same "identity" (an `AttentionState` + reason pair) and both need
to survive a server restart (design doc, issue #6's acceptance criteria: "ack
state survives server restart and resets correctly on a new event"):

- **Acknowledge** -- what the owner last explicitly said "I've seen this" to,
  from the wall or a tab (`control_room.shell.server`'s `/ack` route). Drives
  `control_room.wall.compute_wall_summary`'s `unacknowledged_need_you` and
  `control_room.board.render.render_board`'s `acknowledged` flag -- both stop
  the blink; neither ever writes the CAS/event-log record itself
  (`control_room.attention.store.EventLogStore` is untouched by any of this
  -- ack is local render state, never a ledger write, design doc verbatim).
- **Notify-dedup** -- has an OS notification already fired for this exact
  identity, and when (`control_room.attention.notify.should_notify` reads
  this to decide). Kept distinct from acknowledge because the two acceptance
  criteria they satisfy are different: "never notifies twice for the same
  *unacknowledged* state" must hold even before the owner ever acks anything.

Comparison-based, not a separate boolean flag for "is this stale": a stream
whose identity changes (a new state, or the same state with different
reason text) is unacknowledged/re-notifiable again the instant the new
identity is observed -- no explicit "clear" call needed anywhere for that
case. An explicit clear (`forget`) is still needed for the one case
comparison can't cover on its own: `control_room.shell.state.FleetState`
calls it when a stream's bucket leaves the M bucket entirely, so a *later*
M-bucket episode -- even one that happens to carry identical wording --
reads as genuinely new rather than "still the same old, already-handled
one" (see that module's own reasoning).
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from control_room.attention.models import AttentionEvent, AttentionState

logger = logging.getLogger(__name__)


class AckRecord(BaseModel):
    """One stream's acknowledge + notify-dedup state. All fields `None` is
    the default, "never acknowledged, never notified" starting point --
    exactly what a stream not yet present in the store means (see
    `AckStore.get`)."""

    acknowledged_state: AttentionState | None = None
    acknowledged_reason: str | None = None
    last_notified_state: AttentionState | None = None
    last_notified_reason: str | None = None
    last_notified_at: datetime | None = None

    def is_acknowledged(self, event: AttentionEvent) -> bool:
        return (self.acknowledged_state, self.acknowledged_reason) == (event.state, event.reason)


class AckStore:
    """Disk-backed, thread-safe store of one `AckRecord` per stream id.

    Loaded once at construction -- giving "ack state survives server
    restart" for free -- and written through synchronously on every mutation
    (small file, infrequent writes; same "no server-held state beyond
    ack/preferences, disk is truth" posture `control_room.attention.store.
    EventLogStore` already commits to). Guarded by a lock because, unlike
    that store (written only by short-lived hook-script processes, read only
    by the poll loop), this one is written from *two threads inside the same
    server process*: the poll loop (`control_room.shell.state.FleetState.
    poll`, notify-dedup bookkeeping) and the `/ack` HTTP handler
    (`control_room.shell.server`, the explicit acknowledge action) --
    `ThreadingHTTPServer` gives every request its own thread by design.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._records: dict[str, AckRecord] = self._load()

    def get(self, stream_id: str) -> AckRecord:
        with self._lock:
            return self._records.get(stream_id, AckRecord())

    def put(self, stream_id: str, record: AckRecord) -> None:
        with self._lock:
            self._records[stream_id] = record
            self._save()

    def forget(self, stream_id: str) -> None:
        """Drop a stream's record entirely -- its needs-you episode is over
        (bucket left M) or the stream itself aged out of the fleet."""
        with self._lock:
            if self._records.pop(stream_id, None) is not None:
                self._save()

    def acknowledge(self, stream_id: str, *, state: AttentionState, reason: str | None) -> None:
        """Record that the owner acknowledged `stream_id`'s current identity
        (state + reason) -- called from the `/ack` HTTP handler with the
        identity it read from the latest served payload, never a
        client-supplied one (an owner acking a stream can't accidentally
        forge an identity that was never actually observed)."""
        with self._lock:
            record = self._records.get(stream_id, AckRecord())
            self._records[stream_id] = record.model_copy(
                update={"acknowledged_state": state, "acknowledged_reason": reason}
            )
            self._save()

    def prune(self, live_stream_ids: set[str]) -> None:
        """Drop every record whose stream id is no longer on the fleet --
        mirrors `control_room.shell.state.FleetState`'s own `_previous_event`
        pruning (same unbounded-growth concern, same fix)."""
        with self._lock:
            stale = [sid for sid in self._records if sid not in live_stream_ids]
            if not stale:
                return
            for sid in stale:
                del self._records[sid]
            self._save()

    def _load(self) -> dict[str, AckRecord]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}

        records: dict[str, AckRecord] = {}
        for stream_id, value in raw.items():
            try:
                records[stream_id] = AckRecord.model_validate(value)
            except ValueError:
                logger.warning("dropping unreadable ack record for stream %s", stream_id)
                continue  # one corrupt entry never blinds the whole store
        return records

    def _save(self) -> None:
        """Atomic write: a tmp file + rename, so a crash mid-write never
        leaves a half-written, unparseable ack file for the next `_load`."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {sid: record.model_dump(mode="json") for sid, record in self._records.items()}
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        tmp_path.replace(self._path)
