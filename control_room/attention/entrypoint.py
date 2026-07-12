"""Hook script entry point: `python3 -m control_room.attention.entrypoint`.

Registered against Claude Code's `PreToolUse`/`PostToolUse`/`UserPromptSubmit`/
`Notification`/`Stop` hook events (see `control_room/attention/hooks.json`,
installed per `README.md`) -- reads one hook JSON payload from stdin,
classifies it via `hook_events.classify_hook_payload`, and appends the
result to the local event-log store (`store.EventLogStore`).

Fire-and-forget by design: always exits 0. A hook that blocks or crashes
the owner's own session over a read-only observability side-channel would
violate T1's observe-only posture (design doc: "the operator acts, the tool
never does") -- worse, it would make control-room *less* reliable than the
harness's own notifications it exists to beat. Errors go to stderr only
(visible in Claude Code's own hook-debug output), never to stdout (which
Claude Code may otherwise treat as hook output) and never as a nonzero exit.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from control_room import paths
from control_room.attention.hook_events import classify_hook_payload
from control_room.attention.store import EventLogStore
from control_room.attention.transcripts import (
    TailVerdict,
    classify_transcript_tail,
    read_transcript_entries,
)


def _classify_transcript_path(transcript_path: str) -> TailVerdict:
    return classify_transcript_tail(read_transcript_entries(transcript_path))


def run(raw_stdin: str, *, events_dir: Path | None = None) -> None:
    """Testable core: classify `raw_stdin` and append the result, if any."""
    try:
        payload = json.loads(raw_stdin)
    except json.JSONDecodeError:
        return
    if not isinstance(payload, dict):
        return

    event = classify_hook_payload(payload, classify_transcript_tail=_classify_transcript_path)
    if event is not None:
        EventLogStore(events_dir or paths.attention_events_dir()).append(event)


def main() -> int:
    try:
        run(sys.stdin.read())
    except Exception as exc:
        print(f"control-room attention hook: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
