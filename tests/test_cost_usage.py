"""`control_room.cost.usage`: transcript usage records -> `StreamCost`.

Golden numbers cross-checked against real `~/.claude/projects/*.jsonl`
transcripts and `ccusage`'s own per-session token/cost totals while
building this story (not reproduced here -- these fixtures are synthetic,
matching the real transcript *shapes* observed, per this module's own
docstring on why the last-occurrence-wins dedup rule exists).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from control_room.cost.usage import aggregate_usage, compute_stream_cost, price_usage
from control_room.models import LiveState, StreamKind, StreamRecord

NOW = datetime(2026, 7, 12, 14, 0, 0, tzinfo=UTC)


def _assistant_entry(
    *, message_id: str, model: str, request_id: str = "req-1", **usage_overrides
) -> dict:
    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    usage.update(usage_overrides)
    return {
        "type": "assistant",
        "requestId": request_id,
        "message": {"id": message_id, "model": model, "usage": usage},
    }


def test_aggregate_usage_sums_a_single_message_once():
    entries = [
        _assistant_entry(
            message_id="m1", model="claude-opus-4-5-20251101", input_tokens=10, output_tokens=5
        )
    ]
    totals = aggregate_usage(entries)
    assert totals["claude-opus-4-5-20251101"].input_tokens == 10
    assert totals["claude-opus-4-5-20251101"].output_tokens == 5


def test_aggregate_usage_dedups_repeated_message_keeping_last_occurrence():
    """Real Claude Code transcripts re-flush the same (requestId, message.id)
    several times as content streams in, each repeat's usage growing --
    the *last* one is the true final count (see module docstring)."""
    entries = [
        _assistant_entry(message_id="m1", model="claude-opus-4-5-20251101", output_tokens=1),
        _assistant_entry(message_id="m1", model="claude-opus-4-5-20251101", output_tokens=1),
        _assistant_entry(message_id="m1", model="claude-opus-4-5-20251101", output_tokens=156),
    ]
    totals = aggregate_usage(entries)
    assert totals["claude-opus-4-5-20251101"].output_tokens == 156  # not 158 (a raw sum)


def test_aggregate_usage_keeps_distinct_messages_separate_even_with_same_model():
    entries = [
        _assistant_entry(
            message_id="m1", request_id="r1", model="claude-opus-4-5-20251101", output_tokens=100
        ),
        _assistant_entry(
            message_id="m2", request_id="r2", model="claude-opus-4-5-20251101", output_tokens=50
        ),
    ]
    totals = aggregate_usage(entries)
    assert totals["claude-opus-4-5-20251101"].output_tokens == 150


def test_aggregate_usage_tracks_multiple_models_separately():
    entries = [
        _assistant_entry(message_id="m1", model="claude-opus-4-5-20251101", input_tokens=10),
        _assistant_entry(message_id="m2", model="claude-haiku-4-5-20251001", input_tokens=20),
    ]
    totals = aggregate_usage(entries)
    assert set(totals) == {"claude-opus-4-5-20251101", "claude-haiku-4-5-20251001"}


def test_aggregate_usage_skips_non_assistant_and_malformed_entries():
    entries = [
        {"type": "user"},
        {"type": "assistant", "message": "not-a-dict"},
        {"type": "assistant", "message": {"model": "claude-opus-4-5-20251101"}},  # no usage
        "not-even-a-dict",
    ]
    assert aggregate_usage(entries) == {}


def test_price_usage_of_empty_totals_is_the_honest_none_not_zero():
    cost = price_usage({})
    assert cost.total_usd is None
    assert cost.unpriced_models == ()


def test_price_usage_sums_across_priced_models_and_names_the_unpriced_one():
    entries = [
        _assistant_entry(message_id="m1", model="claude-opus-4-5-20251101", input_tokens=1_000_000),
        _assistant_entry(message_id="m2", model="some-future-vendor-model", input_tokens=1_000_000),
    ]
    cost = price_usage(aggregate_usage(entries))
    assert cost.total_usd == 5.0  # only the priced (opus) portion
    assert cost.unpriced_models == ("some-future-vendor-model",)


def test_price_usage_applies_cache_write_and_cache_read_multipliers():
    entries = [
        _assistant_entry(
            message_id="m1",
            model="claude-opus-4-5-20251101",  # $5/$25/$6.25/$0.50 per Mtok
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cache_creation_input_tokens=1_000_000,
            cache_read_input_tokens=1_000_000,
        )
    ]
    cost = price_usage(aggregate_usage(entries))
    assert cost.total_usd == 5 + 25 + 6.25 + 0.5


def _interactive_stream(cwd: Path, session_id: str) -> StreamRecord:
    return StreamRecord(
        id=f"interactive:{session_id}",
        kind=StreamKind.INTERACTIVE,
        label="s",
        cwd=str(cwd),
        live_state=LiveState.LIVE,
        first_seen=NOW,
        last_seen=NOW,
        source_path=str(cwd / "sessions" / "1.json"),
    )


def _write_transcript(base: Path, cwd: Path, session_id: str, entries: list[dict]) -> Path:
    project_dir = base / str(cwd.resolve()).replace("/", "-")
    project_dir.mkdir(parents=True, exist_ok=True)
    transcript = project_dir / f"{session_id}.jsonl"
    transcript.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return transcript


def test_compute_stream_cost_is_the_honest_placeholder_when_unresolvable(tmp_path):
    stream = _interactive_stream(tmp_path / "nowhere", "sid-1")
    cost = compute_stream_cost(stream, projects_dir=tmp_path / "projects")
    assert cost.total_usd is None


def test_compute_stream_cost_prices_the_top_level_transcript(tmp_path):
    base = tmp_path / "projects"
    cwd = tmp_path / "proj"
    _write_transcript(
        base,
        cwd,
        "sid-1",
        [
            _assistant_entry(
                message_id="m1", model="claude-opus-4-5-20251101", input_tokens=1_000_000
            )
        ],
    )
    stream = _interactive_stream(cwd, "sid-1")

    cost = compute_stream_cost(stream, projects_dir=base)

    assert cost.total_usd == 5.0


def test_compute_stream_cost_includes_dispatched_subagent_spend(tmp_path):
    """Real spend inside a Task-dispatched subagent is still the parent
    stream's spend (unlike attention state, which a subagent must never
    influence) -- verified against real `/work-through`-style session data
    while building this story, where subagent files carried the majority
    of a session's real cost."""
    base = tmp_path / "projects"
    cwd = tmp_path / "proj"
    transcript = _write_transcript(
        base,
        cwd,
        "sid-1",
        [
            _assistant_entry(
                message_id="m1", model="claude-opus-4-5-20251101", output_tokens=1_000_000
            )
        ],
    )
    subagents_dir = transcript.parent / "sid-1" / "subagents"
    subagents_dir.mkdir(parents=True)
    (subagents_dir / "agent-a.jsonl").write_text(
        json.dumps(
            _assistant_entry(
                message_id="m2", model="claude-opus-4-5-20251101", output_tokens=1_000_000
            )
        )
        + "\n",
        encoding="utf-8",
    )
    stream = _interactive_stream(cwd, "sid-1")

    cost = compute_stream_cost(stream, projects_dir=base)

    assert cost.total_usd == 50.0  # 2 * 1M output tokens @ $25/Mtok
