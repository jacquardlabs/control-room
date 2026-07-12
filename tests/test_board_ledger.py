"""Reading gate-ledger's own on-disk epic ledger -- the board protocol's ground truth."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from control_room.board.ledger import (
    SUPPORTED_SCHEMA_VERSION,
    ProtocolVersionMismatch,
    load_epic_ledger,
)


def _write_epic(studious_root: Path, slug: str, payload: dict) -> None:
    epics_dir = studious_root / "epics"
    epics_dir.mkdir(parents=True, exist_ok=True)
    (epics_dir / f"{slug}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_loads_a_well_formed_epic_ledger(tmp_path: Path) -> None:
    _write_epic(
        tmp_path,
        "t1",
        {
            "schemaVersion": SUPPORTED_SCHEMA_VERSION,
            "slug": "t1",
            "status": "running",
            "stories": {
                "stream-discovery": {"status": "landed", "deps": [], "retries": {}, "title": "SD"},
            },
        },
    )
    epic = load_epic_ledger(tmp_path, "t1")
    assert epic.slug == "t1"
    assert epic.stories["stream-discovery"].status == "landed"


def test_missing_ledger_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_epic_ledger(tmp_path, "nonexistent")


def test_unsupported_schema_version_raises_protocol_mismatch(tmp_path: Path) -> None:
    _write_epic(tmp_path, "t1", {"schemaVersion": 99, "slug": "t1", "stories": {}})
    with pytest.raises(ProtocolVersionMismatch) as excinfo:
        load_epic_ledger(tmp_path, "t1")
    assert excinfo.value.found_version == 99


def test_missing_schema_version_raises_protocol_mismatch(tmp_path: Path) -> None:
    _write_epic(tmp_path, "t1", {"slug": "t1", "stories": {}})
    with pytest.raises(ProtocolVersionMismatch):
        load_epic_ledger(tmp_path, "t1")


def test_malformed_json_raises_value_error(tmp_path: Path) -> None:
    epics_dir = tmp_path / "epics"
    epics_dir.mkdir(parents=True)
    (epics_dir / "t1.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_epic_ledger(tmp_path, "t1")


def test_well_formed_json_that_is_not_an_object_raises_value_error(tmp_path: Path) -> None:
    """A ledger file that's valid JSON but not a `{...}` object (e.g. `[]` or
    `null` from a corrupted write) must degrade like any other malformed
    ledger -- never an unhandled `AttributeError` from `.get()` on a list."""
    epics_dir = tmp_path / "epics"
    epics_dir.mkdir(parents=True)
    (epics_dir / "t1.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        load_epic_ledger(tmp_path, "t1")


def test_story_with_unexpected_shape_raises_value_error(tmp_path: Path) -> None:
    _write_epic(
        tmp_path,
        "t1",
        {
            "schemaVersion": SUPPORTED_SCHEMA_VERSION,
            "slug": "t1",
            "stories": {"broken": {"retries": "not-a-dict"}},
        },
    )
    with pytest.raises(ValueError, match="failed validation"):
        load_epic_ledger(tmp_path, "t1")


def test_extra_unknown_fields_are_ignored(tmp_path: Path) -> None:
    """A future gate-ledger field addition (goal/premortem/concurrency/...)
    never breaks this reader -- it only tracks what protocol_adapter uses."""
    _write_epic(
        tmp_path,
        "t1",
        {
            "schemaVersion": SUPPORTED_SCHEMA_VERSION,
            "slug": "t1",
            "stories": {},
            "goal": "ship it",
            "premortem": "docs/whatever.md",
            "concurrency": 3,
        },
    )
    epic = load_epic_ledger(tmp_path, "t1")
    assert epic.stories == {}
