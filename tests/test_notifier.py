"""`format_notification` (pure) and `send_desktop_notification` (the
`osascript` side effect, always mocked here -- never a real notification
during a test run, on any platform).
"""

from __future__ import annotations

import subprocess

import pytest

from control_room.attention.models import AttentionState
from control_room.notifier import format_notification, send_desktop_notification


def test_format_notification_names_stream_state_and_reason() -> None:
    title, body = format_notification("auth-refresh", AttentionState.PARKED, "NEEDS DISCUSSION")
    assert title == "control-room"
    assert body == "auth-refresh parked — NEEDS DISCUSSION"


def test_format_notification_omits_the_dash_when_there_is_no_reason() -> None:
    """`died` events commonly carry no reason -- the body must not show a
    dangling "— " with nothing after it."""
    _, body = format_notification("bg-cleanup", AttentionState.DIED, None)
    assert body == "bg-cleanup died"
    assert "—" not in body


def test_send_desktop_notification_invokes_osascript_with_the_message(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    send_desktop_notification("control-room", "auth-refresh parked — NEEDS DISCUSSION")

    assert len(calls) == 1
    (args, kwargs) = calls[0]
    command = args[0]
    assert command[0] == "osascript"
    assert command[1] == "-e"
    assert "NEEDS DISCUSSION" in command[2]
    assert "control-room" in command[2]
    assert kwargs["timeout"] > 0


def test_send_desktop_notification_escapes_embedded_quotes(monkeypatch) -> None:
    """A reason containing a double quote must not break out of the
    AppleScript string literal it's embedded in."""
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: calls.append(args))
    send_desktop_notification("control-room", 'reason with "quotes" inside')

    script = calls[0][0][2]
    assert '\\"quotes\\"' in script


@pytest.mark.parametrize(
    "exc", [OSError("no osascript"), subprocess.TimeoutExpired("osascript", 5)]
)
def test_send_desktop_notification_never_raises(monkeypatch, exc) -> None:
    """Fire-and-forget by contract: a missing `osascript` (any non-macOS
    host) or a wedged call must never crash the poll loop calling this."""

    def _raise(*args, **kwargs):
        raise exc

    monkeypatch.setattr(subprocess, "run", _raise)
    send_desktop_notification("control-room", "anything")  # must not raise
