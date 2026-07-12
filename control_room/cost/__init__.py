"""Per-stream cost vitals: tokens and burn from transcript usage records.

Current-state numbers only (issue #7: "no thresholds, no warnings -- that's
cctx's lane, after the fact") -- this package answers "what has this stream
cost so far," nothing about whether that's a lot, too much, or trending
anywhere.
"""

from __future__ import annotations

from control_room.cost.models import StreamCost
from control_room.cost.usage import compute_stream_cost

__all__ = ["StreamCost", "compute_stream_cost"]
