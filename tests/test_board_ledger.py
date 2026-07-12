"""Reading gate-ledger's own on-disk epic ledger -- the board protocol's ground truth."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from control_room.board.ledger import (
    SUPPORTED_SCHEMA_VERSION,
    ProtocolVersionMismatch,
    _slugify,
    load_epic_ledger,
    load_work_history,
    work_file_path,
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


# ---------------------------------------------------------------------------
# load_work_history -- gate-ledger's own `work-log` history, the content
# DESIGN.md's "verdict trail" drawer shows. A distinct on-disk store from
# the epic ledger above (`.studious/work/<slug>.json`, not `.studious/epics/`).
# ---------------------------------------------------------------------------


def _write_work(studious_root: Path, filename: str, payload: dict) -> None:
    work_dir = studious_root / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / f"{filename}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_slugify_collapses_the_epic_qualified_double_dash_to_one() -> None:
    """Must match `bin/gate-ledger`'s own `slugify()` exactly -- it collapses
    ANY run of non-alphanumeric characters, including the epic-qualified
    slug's own "--" separator, to a single "-"."""
    assert _slugify("t1--fleet-shell") == "t1-fleet-shell"


def test_slugify_lowercases_and_trims_edges() -> None:
    assert _slugify("  T1__Fleet--Shell!! ") == "t1-fleet-shell"


def test_work_file_path_matches_gate_ledgers_own_layout(tmp_path: Path) -> None:
    path = work_file_path(tmp_path, "t1", "fleet-shell")
    assert path == tmp_path / "work" / "t1-fleet-shell.json"


def test_loads_a_well_formed_work_history(tmp_path: Path) -> None:
    _write_work(
        tmp_path,
        "t1-fleet-shell",
        {
            "schemaVersion": 1,
            "slug": "t1-fleet-shell",
            "history": [
                {"step": "build", "outcome": "DONE", "sha": "abc123", "at": "2026-07-12T20:47:38Z"},
                {"step": "audit", "outcome": "FIX AND RE-AUDIT", "sha": "abc123", "at": None},
                {"step": "audit", "outcome": "PASS", "sha": "def456", "at": "2026-07-12T21:01:04Z"},
            ],
        },
    )
    history = load_work_history(tmp_path, "t1", "fleet-shell")
    assert [e.outcome for e in history] == ["DONE", "FIX AND RE-AUDIT", "PASS"]
    assert history[0].sha == "abc123"


def test_missing_work_file_returns_empty_not_raised(tmp_path: Path) -> None:
    """A story with no work-log entry yet (never dispatched) is the ordinary
    case -- never a fault, unlike the epic ledger's own missing-file
    handling (which raises)."""
    assert load_work_history(tmp_path, "t1", "never-started") == ()


def test_malformed_json_returns_empty_not_raised(tmp_path: Path) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir(parents=True)
    (work_dir / "t1-broken.json").write_text("{not json", encoding="utf-8")
    assert load_work_history(tmp_path, "t1", "broken") == ()


def test_non_object_json_returns_empty_not_raised(tmp_path: Path) -> None:
    _write_work(tmp_path, "t1-broken", {})
    (tmp_path / "work" / "t1-broken.json").write_text("[]", encoding="utf-8")
    assert load_work_history(tmp_path, "t1", "broken") == ()


def test_history_field_not_a_list_returns_empty(tmp_path: Path) -> None:
    _write_work(tmp_path, "t1-weird", {"schemaVersion": 1, "slug": "t1-weird", "history": "oops"})
    assert load_work_history(tmp_path, "t1", "weird") == ()


def test_one_malformed_round_is_skipped_not_fatal_to_the_rest(tmp_path: Path) -> None:
    _write_work(
        tmp_path,
        "t1-mixed",
        {
            "schemaVersion": 1,
            "slug": "t1-mixed",
            "history": [
                {"step": "build", "outcome": "DONE"},
                {"outcome": "missing its step field"},
                {"step": "audit", "outcome": "PASS"},
            ],
        },
    )
    history = load_work_history(tmp_path, "t1", "mixed")
    assert [e.outcome for e in history] == ["DONE", "PASS"]
