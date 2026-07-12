"""OS-level notification delivery -- `osascript` first.

Design doc, "Notifications + acknowledge": "T1 targets `osascript` first;
other platforms aren't committed to this milestone." macOS's own
`display notification` AppleScript command needs no extra dependency and no
network -- consistent with PRODUCT.md's "local and keyless" principle.

Fire-and-forget by contract, same posture as `control_room.attention.
entrypoint`'s hook script: a notification is a side channel on top of a
read-only observability tool, never allowed to crash the poll loop that
calls it. A host with no `osascript` (any non-macOS machine, or a sandboxed
CI runner) degrades to "notification silently didn't fire," logged once at
warning level -- never a crashed server.
"""

from __future__ import annotations

import logging
import subprocess

from control_room.attention.models import AttentionState

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 5
"""Generous for a local AppleScript call, but bounded: the poll loop calling
this must never hang indefinitely on a wedged `osascript` process."""


def format_notification(
    stream_label: str, state: AttentionState, reason: str | None
) -> tuple[str, str]:
    """Build the (title, body) pair every notification uses.

    DESIGN.md, verbatim: "One per state change; body names the stream, the
    state, and the one-clause reason." The title stays a stable, generic
    "control-room" (macOS already groups notifications by app); the body
    carries all three pieces of substance, in the same shape PRODUCT.md's own
    worked example uses ("auth-refresh parked — NEEDS DISCUSSION").
    """
    body = f"{stream_label} {state.value}"
    if reason:
        body += f" — {reason}"
    return "control-room", body


def send_desktop_notification(title: str, message: str) -> None:
    """Show one macOS notification. Never raises."""
    script = (
        f"display notification {_applescript_string(message)} "
        f"with title {_applescript_string(title)}"
    )
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=False,
            capture_output=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("desktop notification failed (%s): %s -- %s", title, message, exc)


def _applescript_string(value: str) -> str:
    """Quote `value` as an AppleScript string literal -- escape backslashes
    first, then double quotes, so a reason/label containing either never
    breaks out of the literal or truncates the message."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
