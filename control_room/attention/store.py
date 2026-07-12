"""Append-only per-stream event log -- the hand-off between the hook script and the poller.

`control_room.attention.entrypoint` (the hook script Claude Code invokes)
is a separate, short-lived process per hook firing; it can't hold state in
memory across invocations, and the poller/detector that later reads
"what's the latest hook-sourced event for this stream" runs in yet another
process again. A plain append-only JSONL file per stream, on disk under
`paths.attention_events_dir()`, is the same "read/write disk truth, no
in-memory server state" posture the rest of control-room already commits
to (design doc: "kill and restart the server mid-anything reconstructs the
screen exactly from disk truth").

One file per stream (not one shared file) avoids interleaved writes from
concurrent streams without needing a lock -- mirrors stream-discovery's own
one-file-per-stream convention (`sessions/<pid>.json`, `jobs/<id>/state.json`).
"""

from __future__ import annotations

from pathlib import Path

from control_room.attention.models import AttentionEvent

_UNSAFE_PATH_CHARS = ("/", "\\")


class EventLogStore:
    """Reads/writes one JSONL event log per stream under `events_dir`."""

    def __init__(self, events_dir: Path) -> None:
        self._events_dir = events_dir

    def append(self, event: AttentionEvent) -> None:
        """Append one event to its stream's log. Creates the dir/file as needed."""
        self._events_dir.mkdir(parents=True, exist_ok=True)
        path = self._path_for(event.stream_id)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(event.model_dump_json())
            fh.write("\n")

    def latest(self, stream_id: str) -> AttentionEvent | None:
        """Return the most recently appended event for `stream_id`, or None.

        A malformed trailing line (a partial write mid-flush) is skipped in
        favor of the last well-formed one, rather than raising -- same
        defensive-read posture as `transcripts.read_transcript_entries`.
        """
        path = self._path_for(stream_id)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return None

        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                return AttentionEvent.model_validate_json(line)
            except ValueError:
                continue
        return None

    def _path_for(self, stream_id: str) -> Path:
        safe_name = stream_id
        for char in _UNSAFE_PATH_CHARS:
            safe_name = safe_name.replace(char, "_")
        return self._events_dir / f"{safe_name}.jsonl"
