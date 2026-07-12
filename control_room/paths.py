"""Disk locations control-room reads from and writes to -- overridable for tests.

`claude_home()`-rooted paths are Claude Code's own tree: control-room only
ever reads there (discovery's "read-only by construction"). `control_room_home()`
is different -- it's control-room's OWN local state, the "local ack/prefs
file" the design doc names as the one thing T1 writes
(`docs/specs/2026-07-11-t1-design.md`: "the operator acts, the tool never
does ... writes nothing but its own local ack/prefs"). The attention event
log (`control_room.attention.store`) lives here, not under `claude_home()`,
so it's never confused with Claude Code's own state.

Mirrors cctx's `CCTX_PROJECTS_DIR` override convention (see
`control_room/vendor/cctx_discovery.py`) so tests never touch the real
`~/.claude` tree.
"""

from __future__ import annotations

import os
from pathlib import Path


def claude_home() -> Path:
    if override := os.environ.get("CONTROL_ROOM_CLAUDE_HOME"):
        return Path(override)
    return Path.home() / ".claude"


def sessions_dir() -> Path:
    """Where the Claude Code CLI itself writes one `<pid>.json` per live process."""
    return claude_home() / "sessions"


def jobs_dir() -> Path:
    """Where the CLI writes one `<id>/state.json` per background job / workflow run."""
    return claude_home() / "jobs"


def projects_dir() -> Path:
    """Where the CLI writes one dir of `*.jsonl` transcripts per project cwd."""
    return claude_home() / "projects"


def control_room_home() -> Path:
    """Root of control-room's OWN local state -- distinct from `claude_home()`."""
    if override := os.environ.get("CONTROL_ROOM_HOME"):
        return Path(override)
    return Path.home() / ".control-room"


def attention_events_dir() -> Path:
    """Where the attention hook script appends one JSONL event log per stream."""
    return control_room_home() / "attention-events"
