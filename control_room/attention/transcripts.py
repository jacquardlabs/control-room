"""Poll-fallback attention classification from a transcript's tail.

Used two ways: (1) directly, on a timer, for streams that can't fire hooks
at all (design doc, "Notifications + acknowledge": "Disk-tail polling
remains the detection path for streams that don't or can't fire hooks
(background tasks, and reconciliation on restart)"); (2) hook-triggered,
from `control_room.attention.hook_events.classify_hook_payload`'s `Stop`
handling -- `Stop` alone only says "the top-level turn ended," not *how* it
ended, so the hook path delegates here rather than duplicating the logic.

The anti-false-amber invariant (PRODUCT.md known problem #2; DESIGN.md:
"Uncertainty degrades to grinding, never to a false amber") is the
load-bearing design constraint in this module: it can assert
`review-ready` (finished, look at it -- advisory, not amber) and a narrow,
best-effort `question-pending` (see `_looks_like_a_question`'s limitation
note), but it never asserts `input-blocked` or `parked` from transcript
content alone -- those require a confirming signal (a `Notification` hook,
or board-protocol data) this module doesn't have access to.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from control_room.attention.models import AttentionState

_BOOKKEEPING_TYPES = frozenset({"permission-mode", "worktree-state", "summary"})
"""Transcript entry `type`s observed in real ~/.claude/projects/*.jsonl
files that aren't a conversational turn at all -- skipped when walking back
to find the tail. Not documented Claude Code internals, just this
detector's own defensive skip-list; entries of any OTHER unrecognized type
are skipped the same way (see `_last_turn`), so a future transcript entry
type this module doesn't know about is ignored, not fatal.
"""

_QUESTION_MAX_CHARS = 300
"""Ceiling on a candidate question's length -- keeps `_looks_like_a_question`
from firing on a long report that merely ends in a rhetorical "?" (the
adversarial-tail trap this detector must not fall into)."""

_END_TURN_STOP_REASONS = frozenset({"end_turn", "max_tokens", "stop_sequence"})
"""Anthropic Messages API `stop_reason` values that mean "the turn is over"
(as opposed to `tool_use`, handled separately below). `max_tokens` and
`stop_sequence` both still count as "stopped, look at it" -- truncation is
a review-ready case (something to look at), not a distinct state this
generic detector has more to say about.
"""


@dataclass(frozen=True)
class TailVerdict:
    """A poll-fallback classification: a state, plus a reason when amber."""

    state: AttentionState
    reason: str | None = None


def read_transcript_entries(path: str | Path) -> list[dict]:
    """Read a transcript JSONL file into a list of parsed entries.

    Malformed lines are skipped, not fatal -- one bad line (a partial write
    mid-flush, say) shouldn't blind the whole classifier. A missing file
    reads as empty (nothing to classify from -- callers degrade to
    `grinding` via `classify_transcript_tail`'s own empty-input handling).
    """
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []

    entries = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def classify_transcript_tail(entries: Sequence[dict]) -> TailVerdict:
    """Classify a transcript's tail into an attention state.

    Walks backward from the end, skipping bookkeeping entries, to find the
    most recent "user" or "assistant" turn and reasons about it
    structurally -- never from freeform text matching alone, except the
    narrow, documented `question-pending` heuristic below.
    """
    turn = _last_turn(entries)
    if turn is None:
        return TailVerdict(AttentionState.GRINDING)  # nothing to go on -- degrade, don't guess

    entry_type, message = turn
    content = message.get("content")
    if not isinstance(content, list) or not content:
        return TailVerdict(AttentionState.GRINDING)

    last_block = content[-1]
    if not isinstance(last_block, dict):
        return TailVerdict(AttentionState.GRINDING)
    block_type = last_block.get("type")

    if entry_type == "user" and block_type == "tool_result":
        # The tool call resolved; the assistant hasn't replied yet in this
        # transcript snapshot -- it's about to continue, not stopped.
        return TailVerdict(AttentionState.GRINDING)

    if entry_type != "assistant":
        return TailVerdict(AttentionState.GRINDING)

    if block_type == "tool_use":
        # THE adversarial case named verbatim by issue #2's acceptance
        # criteria: a tool call with no corresponding tool_result yet is
        # genuinely ambiguous between "still executing" and "blocked on
        # permission" from transcript content alone. Asserting
        # `input-blocked` here would be a guess, not a confirmed signal --
        # that confirmation is the `Notification` hook's job
        # (`hook_events._classify_notification`). Required output: grinding.
        return TailVerdict(AttentionState.GRINDING)

    if block_type != "text":
        return TailVerdict(AttentionState.GRINDING)

    stop_reason = message.get("stop_reason")
    if stop_reason not in _END_TURN_STOP_REASONS:
        # A trailing text block without a turn-ending stop_reason is an
        # unusual/incomplete shape (e.g. a mid-write snapshot) -- degrade
        # rather than guess.
        return TailVerdict(AttentionState.GRINDING)

    text = last_block.get("text") or ""
    if _looks_like_a_question(text):
        return TailVerdict(AttentionState.QUESTION_PENDING, reason=_one_clause(text))

    return TailVerdict(AttentionState.REVIEW_READY)


def _last_turn(entries: Sequence[dict]) -> tuple[str, dict] | None:
    for entry in reversed(entries):
        if not isinstance(entry, dict):
            continue
        entry_type = entry.get("type")
        if entry_type not in ("user", "assistant"):
            continue  # bookkeeping entry or unrecognized type -- keep walking back
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        if not isinstance(message.get("content"), list):
            # A real Messages API turn's `content` is always a block list,
            # even a single plain-text reply -- confirmed against real
            # ~/.claude/projects/*.jsonl data. A `type: "user"` entry whose
            # `content` is a bare string is a local/slash-command
            # invocation (e.g. `<command-name>/reload-plugins...`), not a
            # conversational turn: if the operator's last action in a
            # session was running a local command, this entry sits after
            # the real last turn and must not be mistaken for it -- that
            # misread `grinding` (this module's own safe default for "not
            # a turn at all") and then, if the session process exited,
            # `attention.liveness` promoted it straight to a false `died`,
            # since `grinding` is a mid-flight state and no session/local
            # command truly is. Keep walking back to the real last turn.
            continue
        return entry_type, message
    return None


def _looks_like_a_question(text: str) -> bool:
    """Best-effort, deliberately narrow heuristic -- a documented LIMITATION, not a hidden guess.

    Claude Code's transcript format has no structural marker distinguishing
    "the assistant is asking you something" from "the assistant finished a
    report" -- both are an ordinary `end_turn` text block (the Messages
    API's `stop_reason` vocabulary doesn't distinguish them; verified
    against code.claude.com/docs/en/hooks while building this, no
    dedicated ask-user-question tool was confirmed to exist). This
    heuristic only fires on a short, single, unstructured trailing
    question -- a long report that happens to end in a rhetorical "?" falls
    through to `review-ready` instead, per the anti-false-amber invariant
    applied to the amber/advisory boundary (a false `review-ready` is an
    acceptable miss; a false amber is not). Revisit if Claude Code ever
    ships a structural signal for this.
    """
    stripped = text.strip()
    if not stripped.endswith("?"):
        return False
    if len(stripped) > _QUESTION_MAX_CHARS:
        return False
    if stripped.count("?") > 2:
        return False  # multiple questions reads as an open-ended report, not one crisp ask
    # structured/bulleted report, not a single question:
    return not any(line.lstrip().startswith(("#", "-", "*")) for line in stripped.splitlines())


def _one_clause(text: str) -> str:
    """Trim to the last sentence/clause -- DESIGN.md: "its one-clause reason.\""""
    stripped = text.strip()
    for sep in (". ", "\n"):
        if sep in stripped:
            stripped = stripped.rsplit(sep, 1)[-1]
    return stripped
