"""Golden transcript fixtures per attention state, read from real JSONL files.

`FIXTURES_DIR` holds hand-built transcripts shaped exactly like real
`~/.claude/projects/*/*.jsonl` entries (verified against real on-disk data
while building this). The adversarial fixtures encode issue #2's
acceptance criterion verbatim: an ambiguous tail must degrade to
`grinding`, never a false amber.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from control_room.attention.models import AttentionState
from control_room.attention.transcripts import (
    TailVerdict,
    classify_transcript_tail,
    read_transcript_entries,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "transcripts"


def _classify_fixture(name: str) -> TailVerdict:
    entries = read_transcript_entries(FIXTURES_DIR / name)
    assert entries, f"fixture {name} failed to parse -- test is meaningless if this is empty"
    return classify_transcript_tail(entries)


def test_adversarial_mid_tool_call_degrades_to_grinding_never_a_false_amber() -> None:
    """THE required adversarial fixture (issue #2, verbatim): a tool_use with
    no tool_result yet is genuinely ambiguous between "still executing" and
    "blocked on permission" from transcript content alone -- required
    output is grinding, not a guessed amber.
    """
    verdict = _classify_fixture("grinding__adversarial_mid_tool_call.jsonl")
    assert verdict.state == AttentionState.GRINDING
    assert verdict.reason is None


def test_tool_result_with_no_reply_yet_is_grinding() -> None:
    verdict = _classify_fixture("grinding__tool_result_awaiting_reply.jsonl")
    assert verdict.state == AttentionState.GRINDING


def test_clean_finish_is_review_ready() -> None:
    verdict = _classify_fixture("review_ready__clean_finish.jsonl")
    assert verdict.state == AttentionState.REVIEW_READY
    assert verdict.reason is None


def test_long_structured_report_ending_in_a_question_is_not_a_false_amber() -> None:
    """Adversarial: text ends in "?" -- a naive punctuation heuristic would
    misfire here. Required output is the non-amber `review-ready`, not
    `question-pending`.
    """
    verdict = _classify_fixture("review_ready__adversarial_long_report_ending_in_question.jsonl")
    assert verdict.state == AttentionState.REVIEW_READY


def test_short_clarifying_question_is_question_pending_with_its_reason() -> None:
    verdict = _classify_fixture("question_pending__short_clarifying_question.jsonl")
    assert verdict.state == AttentionState.QUESTION_PENDING
    assert verdict.reason == "Should I key the rate limiter by user ID or by IP address?"


def test_empty_transcript_degrades_to_grinding() -> None:
    assert classify_transcript_tail([]) == TailVerdict(AttentionState.GRINDING)


def test_only_bookkeeping_entries_degrades_to_grinding() -> None:
    entries = [
        {"type": "permission-mode", "timestamp": None},
        {"type": "worktree-state", "timestamp": None},
    ]
    assert classify_transcript_tail(entries) == TailVerdict(AttentionState.GRINDING)


def test_missing_transcript_file_reads_as_empty_not_an_error() -> None:
    assert read_transcript_entries(FIXTURES_DIR / "does-not-exist.jsonl") == []


def test_malformed_json_line_is_skipped_not_fatal(tmp_path: Path) -> None:
    path = tmp_path / "partial.jsonl"
    path.write_text(
        '{"type": "user", "message": {"role": "user", "content": []}}\n{"type": "assistant"',
        encoding="utf-8",
    )
    entries = read_transcript_entries(path)
    assert len(entries) == 1


@pytest.mark.parametrize(
    "text",
    [
        "a" * 301 + "?",  # over the length ceiling, no bullets
        "Did you mean A? Or B? Or C?",  # more than two question marks -- reads as open-ended
    ],
)
def test_question_heuristic_length_and_multi_question_gates(text: str) -> None:
    entries = [
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": text}],
                "stop_reason": "end_turn",
            },
        }
    ]
    verdict = classify_transcript_tail(entries)
    assert verdict.state == AttentionState.REVIEW_READY
