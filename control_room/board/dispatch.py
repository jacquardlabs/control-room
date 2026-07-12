"""Pick an adapter per stream and never let a protocol failure crash the tab.

The one seam that decides "does this stream get the rich board or generic
vitals" -- everything upstream (adapters, renderer) stays ignorant of this
decision. Three outcomes, by design:

1. Not board-protocol-eligible at all (no `epic/<slug>[--<story>]` branch) --
   straight to generic vitals, silently; this is the ordinary case for every
   plain session/task and isn't worth a log line.
2. Eligible, but no epic ledger recorded yet (`/work-through` hasn't run) --
   also generic vitals, also silently; an epic branch existing ahead of any
   recorded run is normal, not a fault.
3. Eligible, a ledger exists, but it's unreadable at a supported version or
   fails validation -- generic vitals, but *loudly*: logged, and flagged on
   the returned `BoardView` (`degraded_from_protocol`) so a renderer can
   surface it. This is the story's "protocol version mismatch degrades to
   generic vitals loudly, never crashes the tab" acceptance criterion,
   applied to any unreadable-ledger failure, not just a version mismatch
   specifically -- the resilience posture is the same either way.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from control_room.attention.models import AttentionEvent
from control_room.board.generic_adapter import build_generic_board
from control_room.board.ledger import ProtocolVersionMismatch, load_epic_ledger
from control_room.board.models import BoardView
from control_room.board.protocol_adapter import build_protocol_board
from control_room.models import StreamRecord

logger = logging.getLogger(__name__)

_EPIC_BRANCH_PREFIX = "epic/"


@dataclass(frozen=True)
class EpicBranchRef:
    """What an `epic/...` branch name identifies -- an epic run, whole or a
    single story's own worktree branch within it."""

    epic_slug: str
    story_slug: str | None


def parse_epic_branch(branch: str | None) -> EpicBranchRef | None:
    """`epic/<epic>` (the integration branch) or `epic/<epic>--<story>` (a
    story worktree branch) -- both name an epic run; only the epic slug
    matters here, since a board tab renders the whole epic, not one story.
    `None` for anything else (a plain feature branch, `main`, detached HEAD).
    """
    if branch is None or not branch.startswith(_EPIC_BRANCH_PREFIX):
        return None
    rest = branch[len(_EPIC_BRANCH_PREFIX) :]
    if not rest:
        return None
    epic_slug, sep, story_slug = rest.partition("--")
    if not epic_slug:
        return None
    return EpicBranchRef(epic_slug=epic_slug, story_slug=story_slug if sep else None)


def resolve_board_view(
    stream: StreamRecord,
    event: AttentionEvent,
    *,
    studious_root: Path | None = None,
) -> BoardView:
    """The one dispatcher: generic vitals unless a readable, supported-version
    epic ledger says otherwise.

    `studious_root` is injected for tests; production callers leave it
    unset so it resolves to `<stream.project_root>/.studious`, mirroring
    `bin/gate-ledger`'s own anchoring to the main working tree.
    """
    ref = parse_epic_branch(stream.git_branch)
    if ref is None or not stream.project_root:
        return build_generic_board(stream, event)

    root = studious_root if studious_root is not None else Path(stream.project_root) / ".studious"

    try:
        epic = load_epic_ledger(root, ref.epic_slug)
    except FileNotFoundError:
        return build_generic_board(stream, event)
    except (ProtocolVersionMismatch, ValueError, OSError) as exc:
        return _degrade(stream, event, exc)

    try:
        return build_protocol_board(epic, stream_id=stream.id)
    except ValueError as exc:
        return _degrade(stream, event, exc)


def _degrade(stream: StreamRecord, event: AttentionEvent, exc: Exception) -> BoardView:
    logger.warning("board protocol degraded to generic vitals for stream %s: %s", stream.id, exc)
    view = build_generic_board(stream, event)
    return view.model_copy(update={"degraded_from_protocol": True, "degraded_reason": str(exc)})
