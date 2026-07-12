"""Read gate-ledger's own on-disk epic ledger -- the board protocol's ground truth.

Studious #98's board schema/renderer never shipped a named contract file
(`board-schema.md`/`events-format.md`) in the studious version this codebase
adopts against; what *does* exist, real and versioned, is `bin/gate-ledger`'s
own on-disk store: `.studious/epics/<slug>.json`, anchored to the main
working tree regardless of which linked worktree reads it (mirroring
`gate-ledger`'s own `repo_root`/`ledger_dir` bash functions verbatim). That
file -- not a separate schema doc -- is "gate-ledger ground truth" the
story's acceptance criteria names, so this module reads it directly: one
`schemaVersion` field, one `stories` map keyed by story slug, each carrying
`status`/`deps`/`retries`/`reason`/`title`. `control_room.board.protocol_adapter`
is the only caller that turns this into a `BoardView`; this module only
parses and version-checks.

Never writes: gate-ledger itself is the sole writer of this file (CLAUDE.md/
PRODUCT.md's read-only-through-T1 posture applies here just as much as to
Claude Code's own on-disk state).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, ValidationError

SUPPORTED_SCHEMA_VERSION = 1
"""The only `schemaVersion` this adapter is validated to read. A ledger file
stamped with any other version -- newer or older -- is a protocol mismatch:
`load_epic_ledger` raises `ProtocolVersionMismatch` rather than guessing at
an unreviewed shape, so `control_room.board.dispatch` can degrade loudly to
generic vitals instead of rendering a wrong or partial board silently."""


class ProtocolVersionMismatch(Exception):
    """Raised when a ledger file's `schemaVersion` isn't one this adapter reads.

    Never raised for a merely *missing* ledger file (`FileNotFoundError`
    propagates for that instead) -- an epic branch with no `/work-through`
    run yet is the ordinary case a stream degrades to generic vitals from
    quietly; a present-but-unreadable-version file is the loud case.
    """

    def __init__(self, found_version: object) -> None:
        self.found_version = found_version
        super().__init__(
            f"epic ledger schemaVersion {found_version!r} is not the supported "
            f"version {SUPPORTED_SCHEMA_VERSION!r}"
        )


class StoryLedger(BaseModel):
    """One story's row in the epic ledger -- gate-ledger's own shape, read verbatim."""

    status: str = "pending"
    deps: tuple[str, ...] = ()
    retries: dict[str, int] = {}
    title: str = ""
    reason: str | None = None


class EpicLedger(BaseModel):
    """The epic ledger file's shape, fields this adapter uses only.

    Extra keys gate-ledger writes (`goal`, `premortem`, `concurrency`, ...)
    are ignored by construction (pydantic's default `extra="ignore"") --
    this reader tracks only what `protocol_adapter` needs, so a future
    gate-ledger field addition never breaks this story's build.
    """

    schema_version: int
    slug: str
    status: str = "planning"
    stories: dict[str, StoryLedger] = {}


def epic_ledger_path(studious_root: Path, epic_slug: str) -> Path:
    """Mirrors `bin/gate-ledger`'s `ledger_dir`-then-`epics/<slug>.json` layout."""
    return studious_root / "epics" / f"{epic_slug}.json"


def load_epic_ledger(studious_root: Path, epic_slug: str) -> EpicLedger:
    """Read and version-check one epic's ledger file.

    Raises `FileNotFoundError` if no ledger exists yet for this epic (the
    ordinary "nothing to enrich with" case) and `ProtocolVersionMismatch` if
    one exists but at a `schemaVersion` this adapter doesn't read. Malformed
    JSON or a shape pydantic can't validate raises `ValueError` (via
    `json.JSONDecodeError`/`pydantic.ValidationError`, both `ValueError`
    subclasses) -- `control_room.board.dispatch` treats all three as
    "degrade to generic," but keeps them distinct here so tests can assert
    on which failure mode fired.
    """
    path = epic_ledger_path(studious_root, epic_slug)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"epic ledger at {path} is not a JSON object")

    found_version = raw.get("schemaVersion")
    if found_version != SUPPORTED_SCHEMA_VERSION:
        raise ProtocolVersionMismatch(found_version)

    try:
        return EpicLedger.model_validate(
            {
                "schema_version": found_version,
                "slug": raw.get("slug", epic_slug),
                "status": raw.get("status", "planning"),
                "stories": raw.get("stories", {}),
            }
        )
    except ValidationError as exc:
        raise ValueError(f"epic ledger at {path} failed validation: {exc}") from exc


class WorkHistoryEntry(BaseModel):
    """One `gate-ledger work-log` entry -- gate-ledger's own shape, read
    verbatim. DESIGN.md's "verdict trail": a story's own build/audit/fix/
    retry history, one round per entry."""

    step: str
    outcome: str
    sha: str | None = None
    at: str | None = None


def _slugify(value: str) -> str:
    """Python port of `bin/gate-ledger`'s own `slugify()`: lowercase, runs
    of anything outside `[a-z0-9]` collapse to one `-`, edges trimmed. Must
    match exactly -- `work_file_path` uses this to name the same on-disk
    file gate-ledger itself writes, and gate-ledger's own `slugify` collapses
    the epic-qualified slug's own "--" separator to a single "-" (e.g.
    `t1--fleet-shell` -> `t1-fleet-shell`) just like any other run of
    non-alphanumeric characters."""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def work_file_path(studious_root: Path, epic_slug: str, story_slug: str) -> Path:
    """Mirrors `bin/gate-ledger`'s own `work_dir`-then-`<slug>.json` layout
    for a story's work file, keyed by the *slugified* epic-qualified slug
    (`_slugify`'s own docstring explains the `--` collapse)."""
    return studious_root / "work" / f"{_slugify(f'{epic_slug}--{story_slug}')}.json"


def load_work_history(
    studious_root: Path, epic_slug: str, story_slug: str
) -> tuple[WorkHistoryEntry, ...]:
    """One story's own build/audit/fix/retry trail -- gate-ledger's own
    `work-log` history, the content DESIGN.md's "verdict trail" drawer
    shows. `()` for anything not cleanly readable (no work file yet, e.g. a
    story that hasn't started, malformed JSON, an unexpected shape) -- a
    trail is enrichment, never load-bearing the way the epic ledger's own
    schema-version check is; a story with nothing to show is the ordinary
    case, not a fault worth degrading the whole board over.
    """
    path = work_file_path(studious_root, epic_slug, story_slug)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    if not isinstance(raw, dict):
        return ()
    history = raw.get("history")
    if not isinstance(history, list):
        return ()

    entries = []
    for item in history:
        try:
            entries.append(WorkHistoryEntry.model_validate(item))
        except ValidationError:
            continue  # one malformed round is skipped, not fatal to the rest
    return tuple(entries)
