"""Disk locations stream discovery reads from -- overridable for tests.

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
