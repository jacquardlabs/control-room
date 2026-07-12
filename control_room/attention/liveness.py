"""Died detection: a stream that goes away mid-flight, not on a clean finish.

Ties into stream-discovery's own liveness bookkeeping
(`control_room.models.LiveState`) without owning it -- discovery decides
*whether a stream is still there at all*; this module only decides whether
its disappearance means `died`.
"""

from __future__ import annotations

from control_room.attention.models import AttentionState
from control_room.models import LiveState

_MIDFLIGHT_STATES = frozenset(
    {AttentionState.GRINDING, AttentionState.INPUT_BLOCKED, AttentionState.QUESTION_PENDING}
)
"""States that mean "still had work outstanding." Losing the process while
here is abnormal (`died`, DESIGN.md: "died -- red; process/agent ended
abnormally"). Losing it after `review-ready`/`done`/`parked` is just normal
cleanup -- the terminal closed after the work already finished --
DESIGN.md's "instruments never move" means a stream that finished
successfully is never retroactively relabeled `died` just because its
process later exited.
"""


def classify_liveness_transition(
    previous_state: AttentionState, live_state: LiveState
) -> AttentionState | None:
    """Return `died` if a mid-flight stream just lost its process, else None.

    `None` means "no liveness override" -- the caller keeps whatever
    hook/poll-derived state it already had. Only `LiveState.GRACE` (not
    `LIVE`) triggers this, matching stream-discovery's own "a single missed
    poll is a blip, not a grade change" posture (`registry._grade`) --
    `died` is asserted only once discovery itself has decided the process
    is genuinely gone, never on the first ambiguous read.
    """
    if live_state == LiveState.GRACE and previous_state in _MIDFLIGHT_STATES:
        return AttentionState.DIED
    return None
