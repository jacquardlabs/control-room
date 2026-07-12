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
