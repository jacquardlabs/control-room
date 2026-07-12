"""Read a Workflow run's own subagent journal for board enrichment.

A distinct concern from `control_room.discovery.workflows` -- that module
reads the same `<session>/subagents/workflows/<run-id>/journal.jsonl` file
only to count started/finished agents for progress labeling and liveness.
This module reads it for richer, per-agent detail: DESIGN.md's drawer,
applied to a Workflow run's own dispatched agents, the generic-adapter
counterpart to `control_room.board.ledger.load_work_history` (a studious
epic's own gate/fix history, for the protocol adapter).
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

_SUMMARY_KEYS = ("summary", "verdict")
"""Real Workflow-tool agent results carry one of these keys for a human-
readable outcome (confirmed against real journal data, 2026-07). Neither is
guaranteed -- a script's own `agent()` call can return a bare string, or a
structured result with neither key -- see `_summarize`'s own fallback."""

_MAX_SUMMARY_LENGTH = 240
"""A drawer row, not a transcript -- long enough to read the gist, short
enough that one agent's own multi-paragraph summary doesn't dominate the
whole disclosure."""


class SubagentResult(BaseModel):
    """One dispatched agent's own outcome, read from a run's own
    `journal.jsonl` -- its id, whether it's finished (a `result` entry
    exists) or still in flight (`started` only), and a short human-
    readable summary when the result carries one."""

    agent_id: str
    done: bool
    summary: str | None = None
    sha: str | None = None


def read_subagent_results(run_dir: Path) -> tuple[SubagentResult, ...]:
    """One `SubagentResult` per agent this run has dispatched, in dispatch
    order -- `()` if the journal can't be read (no run directory, no
    journal yet, malformed JSON). Enrichment, never load-bearing: a
    Workflow run's own attention state/liveness never depends on this.
    """
    try:
        lines = (run_dir / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()

    order: list[str] = []
    latest_result: dict[str, object] = {}
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        agent_id = entry.get("agentId")
        entry_type = entry.get("type")
        if not isinstance(agent_id, str) or entry_type not in ("started", "result"):
            continue
        if agent_id not in latest_result:
            order.append(agent_id)
            latest_result[agent_id] = None  # not done yet
        if entry_type == "result":
            latest_result[agent_id] = entry.get("result")

    return tuple(_subagent_result(agent_id, latest_result[agent_id]) for agent_id in order)


def _subagent_result(agent_id: str, result: object) -> SubagentResult:
    if result is None:
        return SubagentResult(agent_id=agent_id, done=False)
    summary, sha = _summarize(result)
    return SubagentResult(agent_id=agent_id, done=True, summary=summary, sha=sha)


def _summarize(result: object) -> tuple[str | None, str | None]:
    """A short display string plus a sha, from whatever shape a script's
    own `agent()` call returned -- a bare string, or a structured result
    dict. Never guesses at a summary that isn't there: an unrecognized
    shape (a list, a number, a dict with neither a known summary key nor a
    sha) degrades to `(None, None)`, same "no file, no guess" posture as
    everywhere else in this codebase."""
    if isinstance(result, str):
        text = result.strip()
        return (_truncate(text) if text else None), None
    if isinstance(result, dict):
        sha = result.get("sha") if isinstance(result.get("sha"), str) else None
        for key in _SUMMARY_KEYS:
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return _truncate(value.strip()), sha
        return None, sha
    return None, None


def _truncate(text: str) -> str:
    if len(text) <= _MAX_SUMMARY_LENGTH:
        return text
    return text[: _MAX_SUMMARY_LENGTH - 1].rstrip() + "…"
