"""The wire shape: one `FleetSnapshot` in, one JSON-serializable payload out.

The static page (`static/index.html`) is the only consumer -- it never
re-derives attention state, buckets, or board markup client-side; every
field here is already-resolved server truth (`board_html` is the exact
fragment `control_room.board.render.render_board` produced, escaped and
ready for `innerHTML`). Keeping this as its own Pydantic model, not just
`FleetSnapshot.__dict__`, pins the wire contract explicitly so a later
change to the internal dataclasses can't silently change what the page
receives.
"""

from __future__ import annotations

from pydantic import BaseModel

from control_room.attention.models import AttentionState
from control_room.board.bucket import WallBucket, wall_bucket
from control_room.models import LiveState, StreamKind
from control_room.shell.state import FleetSnapshot
from control_room.wall import WallSummary


class StreamPayload(BaseModel):
    id: str
    label: str
    kind: StreamKind
    attention_state: AttentionState
    reason: str | None
    live_state: LiveState
    board_html: str
    bucket: WallBucket | None
    """The stream's wall bucket (N/R/M), or `None` for `done` -- computed
    once here via `control_room.board.bucket.wall_bucket`, the single owner
    of the seven-state-to-bucket mapping (epic pre-mortem #3). The client
    reads this field rather than re-deriving the mapping from
    `attention_state` itself: a second, hand-copied mapping in
    `static/index.html` is exactly the duplication that pre-mortem names as
    a drift risk -- if a new attention state were ever added, only this one
    function would need updating, not a client-side twin of it."""


class WallPayload(BaseModel):
    grinding: int
    review_ready: int
    need_you: int
    unacknowledged_need_you: int
    master_caution: bool
    aggregate_burn_usd: float | None


class FleetPayload(BaseModel):
    generated_at: str
    """ISO-8601, UTC -- the client's own liveness clock compares against this."""
    poll_interval_seconds: float
    """Echoes the server's actual tick cadence so the client's liveness
    indicator can size its own "stalled" threshold off the real interval
    (e.g. `--poll-interval` at launch) rather than a guessed constant."""
    wall: WallPayload
    streams: tuple[StreamPayload, ...]


def build_fleet_payload(snapshot: FleetSnapshot, *, poll_interval_seconds: float) -> FleetPayload:
    return FleetPayload(
        generated_at=snapshot.generated_at.isoformat(),
        poll_interval_seconds=poll_interval_seconds,
        wall=_wall_payload(snapshot.wall),
        streams=tuple(
            StreamPayload(
                id=item.stream.id,
                label=item.stream.label,
                kind=item.stream.kind,
                attention_state=item.event.state,
                reason=item.event.reason,
                live_state=item.stream.live_state,
                board_html=item.board_html,
                bucket=wall_bucket(item.event.state),
            )
            for item in snapshot.streams
        ),
    )


def _wall_payload(summary: WallSummary) -> WallPayload:
    return WallPayload(
        grinding=summary.grinding,
        review_ready=summary.review_ready,
        need_you=summary.need_you,
        unacknowledged_need_you=summary.unacknowledged_need_you,
        master_caution=summary.master_caution,
        aggregate_burn_usd=summary.aggregate_burn_usd,
    )
