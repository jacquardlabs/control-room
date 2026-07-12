"""control_room_home()/attention_events_dir() -- control-room's own local state, not `~/.claude`."""

from __future__ import annotations

from pathlib import Path

from control_room import paths


def test_control_room_home_defaults_to_dotfile_under_home(monkeypatch) -> None:
    monkeypatch.delenv("CONTROL_ROOM_HOME", raising=False)
    assert paths.control_room_home() == Path.home() / ".control-room"


def test_control_room_home_honors_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CONTROL_ROOM_HOME", str(tmp_path))
    assert paths.control_room_home() == tmp_path


def test_attention_events_dir_is_under_control_room_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CONTROL_ROOM_HOME", str(tmp_path))
    assert paths.attention_events_dir() == tmp_path / "attention-events"


def test_control_room_home_is_distinct_from_claude_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CONTROL_ROOM_HOME", str(tmp_path / "control-room"))
    monkeypatch.setenv("CONTROL_ROOM_CLAUDE_HOME", str(tmp_path / "claude"))
    assert paths.control_room_home() != paths.claude_home()
