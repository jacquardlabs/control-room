"""The hook script's testable core (`run`): stdin JSON -> event-log append.

Fire-and-forget by design (module docstring): malformed input must never
raise, only ever produce "nothing appended."
"""

from __future__ import annotations

import json
from pathlib import Path

from control_room.attention.entrypoint import main, run
from control_room.attention.models import AttentionState
from control_room.attention.store import EventLogStore


def test_pretooluse_payload_appends_a_grinding_event(tmp_path: Path) -> None:
    payload = {"session_id": "abc123", "hook_event_name": "PreToolUse", "tool_name": "Bash"}
    run(json.dumps(payload), events_dir=tmp_path)
    event = EventLogStore(tmp_path).latest("abc123")
    assert event is not None
    assert event.state == AttentionState.GRINDING


def test_subagent_scoped_payload_appends_nothing(tmp_path: Path) -> None:
    payload = {"session_id": "abc123", "hook_event_name": "PreToolUse", "agent_id": "sub-1"}
    run(json.dumps(payload), events_dir=tmp_path)
    assert EventLogStore(tmp_path).latest("abc123") is None


def test_malformed_json_never_raises(tmp_path: Path) -> None:
    run("not json at all {{{", events_dir=tmp_path)  # must not raise


def test_json_array_instead_of_object_never_raises(tmp_path: Path) -> None:
    run("[1, 2, 3]", events_dir=tmp_path)  # must not raise


def test_main_never_raises_and_always_returns_zero(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CONTROL_ROOM_HOME", str(tmp_path))
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("not json"))
    assert main() == 0
