"""Turn a transcript's own usage records into one `StreamCost`.

Reuses `control_room.attention.transcripts.read_transcript_entries` (never a
second JSONL reader -- a missing/malformed transcript already degrades to
`[]` there, so this module inherits that same "no file, no guess" behavior
for free) and `control_room.transcript_locator.resolve_all_transcript_paths`
(the top-level conversation plus every Task-dispatched subagent transcript
nested under it -- see that function's own docstring for why cost
accounting, unlike attention detection, needs every subagent file too).

**Known limitation, named rather than hidden:** every poll re-reads and
re-aggregates every one of a stream's transcript files from scratch --
correct (each file's usage records are immutable once written, so this
never drifts), but not incremental. A long-running stream with heavy
Task/subagent fan-out (dozens of nested transcript files, as observed while
building this against a real `/work-through`-style session) means this
cost scales with total transcript bytes on disk, re-paid every poll tick
(`shell.state.FleetState`'s cadence) for as long as the stream lives.
Acceptable for a first correct cut -- no acceptance criterion here is about
latency -- but a real optimization opportunity for later: cache each file's
computed per-model totals keyed by `(path, mtime, size)` and only re-read
files that changed since the last poll.

**Why dedup by `(requestId, message.id)`, keeping the *last* occurrence:**
Claude Code's own transcript format writes the *same* assistant message more
than once as its content streams in (observed directly in real
`~/.claude/projects/*.jsonl` files while building this: one message id
repeated 2-9+ times in a row). Summing every line would overcount a
session's real spend by however many times its longest message happened to
be re-flushed -- but the repeats are NOT always byte-identical: cross-
checked against a second real transcript (and against `ccusage`'s own
per-session token totals for it), a message's `usage.output_tokens` and
cache fields grow across its own repeats as more content streams in (e.g.
`1 -> 1 -> 156`), with the *last* occurrence carrying the true final count.
Keeping the first occurrence instead (this module's first draft) silently
undercounted output/cache tokens by however early the first flush landed --
caught here specifically because two real transcripts disagreed with each
other on whether repeats were identical, not something a single fixture
would have surfaced. `requestId` is included alongside the message id (not
just the id alone) as a defensive extra key -- a message id colliding
across two distinct API requests would be a startling and expensive bug to
alias silently.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from control_room.attention.transcripts import read_transcript_entries
from control_room.cost.models import StreamCost
from control_room.cost.pricing import lookup_rates
from control_room.models import StreamRecord
from control_room.transcript_locator import resolve_all_transcript_paths


@dataclass
class _ModelUsage:
    """Running token totals for one model, summed across a transcript's
    deduplicated assistant messages (one final `usage` snapshot per
    distinct message, never a raw per-line sum)."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    def add(self, usage: dict) -> None:
        self.input_tokens += _int_field(usage, "input_tokens")
        self.output_tokens += _int_field(usage, "output_tokens")
        self.cache_creation_tokens += _int_field(usage, "cache_creation_input_tokens")
        self.cache_read_tokens += _int_field(usage, "cache_read_input_tokens")


def _int_field(usage: dict, key: str) -> int:
    value = usage.get(key)
    return value if isinstance(value, int) else 0


def aggregate_usage(entries: Sequence[dict]) -> dict[str, _ModelUsage]:
    """Sum token usage per model across `entries`, counting each distinct
    `(requestId, message.id)` assistant message exactly once, using its
    *last* (final, largest) `usage` snapshot -- see module docstring."""
    last_usage: dict[tuple[str, str], tuple[str, dict]] = {}

    for entry in entries:
        if not isinstance(entry, dict) or entry.get("type") != "assistant":
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            continue

        model = message.get("model")
        usage = message.get("usage")
        message_id = message.get("id")
        if not model or not isinstance(usage, dict) or not message_id:
            continue

        dedup_key = (str(entry.get("requestId") or ""), str(message_id))
        last_usage[dedup_key] = (model, usage)  # overwrite -- last occurrence wins

    totals: dict[str, _ModelUsage] = {}
    for model, usage in last_usage.values():
        totals.setdefault(model, _ModelUsage()).add(usage)
    return totals


def price_usage(usage_by_model: dict[str, _ModelUsage]) -> StreamCost:
    """Price each model's totals via `pricing.lookup_rates`, summing the
    priced portion and naming any model that couldn't be priced at all."""
    if not usage_by_model:
        return StreamCost()

    total = 0.0
    priced_any = False
    unpriced: list[str] = []

    for model, usage in usage_by_model.items():
        rates = lookup_rates(model)
        if rates is None:
            unpriced.append(model)
            continue
        priced_any = True
        total += (
            usage.input_tokens * rates.input
            + usage.output_tokens * rates.output
            + usage.cache_creation_tokens * rates.cache_write
            + usage.cache_read_tokens * rates.cache_read
        )

    return StreamCost(
        total_usd=total if priced_any else None,
        unpriced_models=tuple(unpriced),
    )


def compute_transcript_cost(entries: Sequence[dict]) -> StreamCost:
    """The whole pipeline for a transcript already read into memory."""
    return price_usage(aggregate_usage(entries))


def compute_stream_cost(stream: StreamRecord, *, projects_dir: Path | None = None) -> StreamCost:
    """The whole pipeline for one `StreamRecord`: resolve every transcript
    file real spend for it was recorded into (top-level conversation plus
    any dispatched-subagent files), read them, price the combined usage.
    `StreamCost()` (all `None`/empty) whenever no transcript can be
    resolved at all -- the same "no file, no guess" posture
    `transcript_locator.resolve_all_transcript_paths` and
    `attention.transcripts.read_transcript_entries` already commit to.
    """
    paths = resolve_all_transcript_paths(stream, projects_dir=projects_dir)
    if not paths:
        return StreamCost()
    entries = [entry for path in paths for entry in read_transcript_entries(path)]
    return compute_transcript_cost(entries)
