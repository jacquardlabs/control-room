"""Reading a Workflow run's own dispatched-agent journal for board
enrichment -- the generic-adapter counterpart to
`control_room.board.ledger.load_work_history` (a studious epic's own
gate/fix history, for the protocol adapter).
"""

from __future__ import annotations

import json
from pathlib import Path

from control_room.board.journal import read_subagent_results


def _write_journal(run_dir: Path, lines: list[dict]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "journal.jsonl").write_text(
        "\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8"
    )


def test_a_finished_agent_with_a_summary_result(tmp_path: Path) -> None:
    _write_journal(
        tmp_path,
        [
            {"type": "started", "agentId": "a1"},
            {
                "type": "result",
                "agentId": "a1",
                "result": {"summary": "did the thing", "sha": "abc123"},
            },
        ],
    )
    (result,) = read_subagent_results(tmp_path)
    assert result.agent_id == "a1"
    assert result.done is True
    assert result.summary == "did the thing"
    assert result.sha == "abc123"


def test_a_result_with_verdict_but_no_summary_uses_verdict(tmp_path: Path) -> None:
    _write_journal(
        tmp_path,
        [
            {"type": "started", "agentId": "a1"},
            {"type": "result", "agentId": "a1", "result": {"verdict": "PROCEED TO PLAN"}},
        ],
    )
    (result,) = read_subagent_results(tmp_path)
    assert result.summary == "PROCEED TO PLAN"


def test_a_bare_string_result_is_used_directly(tmp_path: Path) -> None:
    _write_journal(
        tmp_path,
        [
            {"type": "started", "agentId": "a1"},
            {"type": "result", "agentId": "a1", "result": "just a plain string result"},
        ],
    )
    (result,) = read_subagent_results(tmp_path)
    assert result.summary == "just a plain string result"
    assert result.sha is None


def test_an_agent_with_only_started_is_not_done(tmp_path: Path) -> None:
    _write_journal(tmp_path, [{"type": "started", "agentId": "a1"}])
    (result,) = read_subagent_results(tmp_path)
    assert result.agent_id == "a1"
    assert result.done is False
    assert result.summary is None


def test_a_result_with_neither_summary_nor_verdict_has_no_summary_but_is_done(
    tmp_path: Path,
) -> None:
    """An unrecognized result shape must never be guessed at -- `done` is
    still true (a result entry did arrive), but there's nothing to show."""
    _write_journal(
        tmp_path,
        [
            {"type": "started", "agentId": "a1"},
            {"type": "result", "agentId": "a1", "result": {"unexpected_key": 42}},
        ],
    )
    (result,) = read_subagent_results(tmp_path)
    assert result.done is True
    assert result.summary is None


def test_long_summary_is_truncated(tmp_path: Path) -> None:
    long_text = "x" * 500
    _write_journal(
        tmp_path,
        [
            {"type": "started", "agentId": "a1"},
            {"type": "result", "agentId": "a1", "result": {"summary": long_text}},
        ],
    )
    (result,) = read_subagent_results(tmp_path)
    assert len(result.summary) <= 240
    assert result.summary.endswith("…")


def test_preserves_dispatch_order_across_multiple_agents(tmp_path: Path) -> None:
    _write_journal(
        tmp_path,
        [
            {"type": "started", "agentId": "a1"},
            {"type": "started", "agentId": "a2"},
            {"type": "result", "agentId": "a1", "result": {"summary": "first"}},
            {"type": "result", "agentId": "a2", "result": {"summary": "second"}},
        ],
    )
    results = read_subagent_results(tmp_path)
    assert [r.agent_id for r in results] == ["a1", "a2"]


def test_a_result_with_no_matching_started_entry_still_appears(tmp_path: Path) -> None:
    """A defensive case, not the ordinary one -- if a `result` line somehow
    arrives with no preceding `started` line for the same agent, it must
    still surface rather than being silently dropped."""
    _write_journal(
        tmp_path, [{"type": "result", "agentId": "a1", "result": {"summary": "done anyway"}}]
    )
    (result,) = read_subagent_results(tmp_path)
    assert result.done is True
    assert result.summary == "done anyway"


def test_missing_journal_returns_empty(tmp_path: Path) -> None:
    assert read_subagent_results(tmp_path / "does-not-exist") == ()


def test_malformed_journal_line_is_skipped_not_raised(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "journal.jsonl").write_text(
        "{not json\n" + json.dumps({"type": "started", "agentId": "a1"}) + "\n", encoding="utf-8"
    )
    (result,) = read_subagent_results(tmp_path)
    assert result.agent_id == "a1"


def test_non_dict_result_value_yields_no_summary(tmp_path: Path) -> None:
    _write_journal(
        tmp_path,
        [
            {"type": "started", "agentId": "a1"},
            {"type": "result", "agentId": "a1", "result": [1, 2, 3]},
        ],
    )
    (result,) = read_subagent_results(tmp_path)
    assert result.done is True
    assert result.summary is None
    assert result.sha is None
