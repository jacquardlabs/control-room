"""The stream registry: merges kind-specific discoverers into one liveness-tracked list.

Every `poll()` call re-scans disk from scratch (no incremental caching), so
a new stream is picked up on the very next poll -- the mechanism behind
"all N streams appear within one poll interval." Liveness bookkeeping
(live -> grace -> gone) is the registry's own state, carried across calls
by stream id; the kind-specific discoverers never see or set it.

Discovery is read-only by construction: every read here is a `glob`/`stat`/
`read_text`/`os.kill(pid, 0)` probe -- nothing in this module ever writes,
creates, or deletes anything on disk.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from control_room.discovery.interactive import discover_interactive_sessions, pid_is_alive
from control_room.discovery.jobs import discover_jobs, job_activity_mtime
from control_room.models import LiveState, StreamKind, StreamRecord

GRACE_AFTER_MISSES = 2
"""Consecutive missed-liveness polls before a stream visibly grays.

Pinned to the stream-discovery acceptance criterion verbatim: "a killed
session grays within 2 intervals."
"""

GONE_AFTER_MISSES = 4
"""Consecutive missed-liveness polls before a stream ages out (is dropped).

Not pinned exactly by the acceptance criteria -- the design doc names
threshold-tuning as an explicit plan-phase question for a related
mechanism (notification debounce) and the same reasoning applies here.
Chosen as two more misses past `GRACE_AFTER_MISSES` so a stream is visibly
grayed for at least one full poll before it can disappear -- never a
live-to-gone jump in one interval.
"""

IsProtected = Callable[[StreamRecord], bool]


def _grade(consecutive_misses: int) -> LiveState:
    """A single missed poll is a blip, not a grade change -- only sustained loss grays."""
    return LiveState.GRACE if consecutive_misses >= GRACE_AFTER_MISSES else LiveState.LIVE


class StreamRegistry:
    """Holds liveness bookkeeping across polls. Not thread-safe -- call from one loop."""

    def __init__(self, sessions_dir: Path, jobs_dir: Path) -> None:
        self._sessions_dir = sessions_dir
        self._jobs_dir = jobs_dir
        self._known: dict[str, StreamRecord] = {}
        self._last_job_mtime: dict[str, float] = {}

    def poll(
        self,
        *,
        is_protected: IsProtected | None = None,
        now: datetime | None = None,
    ) -> list[StreamRecord]:
        """Re-scan disk and return the current, liveness-graded stream list.

        A stream still discoverable on disk but showing no evidence of
        life accumulates `consecutive_misses`; at `GRACE_AFTER_MISSES` it
        grays, at `GONE_AFTER_MISSES` it is dropped from the returned list
        -- unless `is_protected(record)` returns True, in which case it
        stays at `grace` forever (the "never disappearing while amber"
        invariant). `is_protected` defaults to "nothing is protected" since
        this story doesn't yet know the attention taxonomy; the
        attention-detection story supplies a real predicate.
        """
        now = now or datetime.now(UTC)
        protected = is_protected or (lambda _record: False)

        discovered_by_id = {r.id: r for r in self._discover_all(now=now)}

        merged: dict[str, StreamRecord] = {}
        for stream_id, discovered in discovered_by_id.items():
            merged[stream_id] = self._advance(stream_id, discovered, now=now)

        # A stream whose disk artifact vanished outright (e.g. the CLI
        # deleted `sessions/<pid>.json` on clean exit) still ages out
        # through the same miss counter -- never dropped on the very
        # first missed poll.
        for stream_id, previous in self._known.items():
            if stream_id in merged:
                continue
            misses = previous.consecutive_misses + 1
            merged[stream_id] = previous.model_copy(
                update={"live_state": _grade(misses), "consecutive_misses": misses}
            )

        survivors = {
            stream_id: record
            for stream_id, record in merged.items()
            if record.consecutive_misses < GONE_AFTER_MISSES or protected(record)
        }

        # `_known` keeps every stream `_advance` has ever graded -- aged-out
        # ones included, not just survivors. A job (or session) whose disk
        # artifact is never deleted after it finishes stays *discoverable*
        # forever; if aged-out entries were dropped from `_known`, the next
        # poll's `_advance` would see `previous is None` for it and treat a
        # merely-quiet, already-graded stream as brand new again -- misses
        # reset to 0, it flickers back in, ages out again four polls later,
        # forever. Keeping the graded record (not re-deriving it as fresh)
        # is what makes "ages out" a one-way trip instead of a repeating
        # cycle; only `survivors` -- filtered here -- is ever returned.
        self._known = merged
        return sorted(survivors.values(), key=lambda r: r.id)

    def _advance(self, stream_id: str, discovered: StreamRecord, *, now: datetime) -> StreamRecord:
        alive_now = self._has_evidence_of_life(stream_id, discovered)
        previous = self._known.get(stream_id)

        if previous is None:
            return discovered.model_copy(
                update={
                    "first_seen": now,
                    "last_seen": now,
                    "live_state": LiveState.LIVE,
                    "consecutive_misses": 0,
                }
            )

        misses = 0 if alive_now else previous.consecutive_misses + 1
        return discovered.model_copy(
            update={
                "first_seen": previous.first_seen,
                "last_seen": now if alive_now else previous.last_seen,
                "live_state": _grade(misses),
                "consecutive_misses": misses,
            }
        )

    def _discover_all(self, *, now: datetime) -> list[StreamRecord]:
        return [
            *discover_interactive_sessions(self._sessions_dir, now=now),
            *discover_jobs(self._jobs_dir, now=now),
        ]

    def _has_evidence_of_life(self, stream_id: str, record: StreamRecord) -> bool:
        if record.kind == StreamKind.INTERACTIVE:
            return pid_is_alive(record.pid)

        current_mtime = job_activity_mtime(Path(record.source_path))
        previous_mtime = self._last_job_mtime.get(stream_id)
        self._last_job_mtime[stream_id] = current_mtime
        if previous_mtime is None:
            return True  # first observation -- nothing to compare against yet
        return current_mtime > previous_mtime
