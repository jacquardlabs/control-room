"""The one seam that picks protocol vs. generic per stream, and never crashes the tab."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from control_room.attention.models import AttentionEvent, AttentionSource, AttentionState
from control_room.board.dispatch import EpicBranchRef, parse_epic_branch, resolve_board_view
from control_room.board.ledger import SUPPORTED_SCHEMA_VERSION
from control_room.board.models import BoardSource
from control_room.models import StreamKind, StreamRecord

_NOW = datetime(2026, 7, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("branch", "expected"),
    [
        (None, None),
        ("main", None),
        ("feature/some-thing", None),
        ("epic/t1", EpicBranchRef(epic_slug="t1", story_slug=None)),
        (
            "epic/t1--board-protocol-render",
            EpicBranchRef(epic_slug="t1", story_slug="board-protocol-render"),
        ),
        ("epic/", None),
    ],
)
def test_parse_epic_branch(branch: str | None, expected: EpicBranchRef | None) -> None:
    assert parse_epic_branch(branch) == expected


def _stream(**overrides: object) -> StreamRecord:
    defaults = {
        "id": "interactive:abc",
        "kind": StreamKind.INTERACTIVE,
        "label": "my-session",
        "cwd": "/repo",
        "project_root": "/repo",
        "git_branch": "epic/t1--board-protocol-render",
        "first_seen": _NOW,
        "last_seen": _NOW,
        "source_path": "/repo/.git/sessions/1.json",
    }
    defaults.update(overrides)
    return StreamRecord(**defaults)


def _event(stream: StreamRecord, **overrides: object) -> AttentionEvent:
    defaults = {
        "stream_id": stream.id,
        "state": AttentionState.GRINDING,
        "source": AttentionSource.POLL,
        "at": _NOW,
    }
    defaults.update(overrides)
    return AttentionEvent(**defaults)


def _write_epic(studious_root: Path, slug: str, payload: dict) -> None:
    epics_dir = studious_root / "epics"
    epics_dir.mkdir(parents=True, exist_ok=True)
    (epics_dir / f"{slug}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_non_epic_branch_goes_straight_to_generic(tmp_path: Path) -> None:
    stream = _stream(git_branch="main")
    view = resolve_board_view(stream, _event(stream), studious_root=tmp_path)
    assert view.source is BoardSource.GENERIC
    assert not view.degraded_from_protocol


def test_no_project_root_goes_straight_to_generic(tmp_path: Path) -> None:
    stream = _stream(project_root=None)
    view = resolve_board_view(stream, _event(stream), studious_root=tmp_path)
    assert view.source is BoardSource.GENERIC


def test_epic_branch_with_no_ledger_yet_degrades_quietly(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    stream = _stream()
    with caplog.at_level(logging.WARNING):
        view = resolve_board_view(stream, _event(stream), studious_root=tmp_path)
    assert view.source is BoardSource.GENERIC
    assert not view.degraded_from_protocol
    assert caplog.records == []  # no ledger yet is ordinary, not a fault


def test_epic_branch_with_matching_ledger_gets_protocol_view(tmp_path: Path) -> None:
    _write_epic(
        tmp_path,
        "t1",
        {
            "schemaVersion": SUPPORTED_SCHEMA_VERSION,
            "slug": "t1",
            "stories": {"board-protocol-render": {"status": "pending", "title": "BPR"}},
        },
    )
    stream = _stream()
    view = resolve_board_view(stream, _event(stream), studious_root=tmp_path)
    assert view.source is BoardSource.PROTOCOL
    assert view.stream_id == stream.id
    assert not view.degraded_from_protocol


def test_version_mismatch_degrades_loudly_never_crashes(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _write_epic(tmp_path, "t1", {"schemaVersion": 999, "slug": "t1", "stories": {}})
    stream = _stream()
    with caplog.at_level(logging.WARNING):
        view = resolve_board_view(stream, _event(stream), studious_root=tmp_path)
    assert view.source is BoardSource.GENERIC
    assert view.degraded_from_protocol
    assert view.degraded_reason is not None
    assert any("degraded" in r.message for r in caplog.records)


def test_malformed_ledger_json_degrades_loudly_never_crashes(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    epics_dir = tmp_path / "epics"
    epics_dir.mkdir(parents=True)
    (epics_dir / "t1.json").write_text("{not json", encoding="utf-8")
    stream = _stream()
    with caplog.at_level(logging.WARNING):
        view = resolve_board_view(stream, _event(stream), studious_root=tmp_path)
    assert view.source is BoardSource.GENERIC
    assert view.degraded_from_protocol
    assert caplog.records


def test_ledger_data_that_fails_the_amber_reason_invariant_degrades_not_crashes(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A parked story with no reason recorded is malformed protocol data (the
    driver always writes `--reason`) -- building the protocol board raises,
    dispatch must still not propagate that as a crash."""
    _write_epic(
        tmp_path,
        "t1",
        {
            "schemaVersion": SUPPORTED_SCHEMA_VERSION,
            "slug": "t1",
            "stories": {"board-protocol-render": {"status": "parked", "title": "BPR"}},
        },
    )
    stream = _stream()
    with caplog.at_level(logging.WARNING):
        view = resolve_board_view(stream, _event(stream), studious_root=tmp_path)
    assert view.source is BoardSource.GENERIC
    assert view.degraded_from_protocol
    assert caplog.records


def test_default_studious_root_derives_from_project_root(tmp_path: Path) -> None:
    """No explicit `studious_root` -- resolves to `<project_root>/.studious`,
    mirroring `bin/gate-ledger`'s own anchoring to the main working tree."""
    project_root = tmp_path / "myproject"
    _write_epic(
        project_root / ".studious",
        "t1",
        {
            "schemaVersion": SUPPORTED_SCHEMA_VERSION,
            "slug": "t1",
            "stories": {"a": {"status": "landed", "title": "A"}},
        },
    )
    stream = _stream(project_root=str(project_root))
    view = resolve_board_view(stream, _event(stream))
    assert view.source is BoardSource.PROTOCOL


def test_studious_root_threads_through_to_populate_verdict_trail(tmp_path: Path) -> None:
    """The one production wiring point: `resolve_board_view` already has
    `studious_root` in scope to load the epic ledger -- it must pass the
    same root through to `build_protocol_board` so a story's own verdict
    trail (gate-ledger's `work-log` history) reaches the board too."""
    _write_epic(
        tmp_path,
        "t1",
        {
            "schemaVersion": SUPPORTED_SCHEMA_VERSION,
            "slug": "t1",
            "stories": {"board-protocol-render": {"status": "landed", "title": "BPR"}},
        },
    )
    work_dir = tmp_path / "work"
    work_dir.mkdir(parents=True)
    (work_dir / "t1-board-protocol-render.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "slug": "t1-board-protocol-render",
                "history": [{"step": "build", "outcome": "DONE", "sha": "abc123"}],
            }
        ),
        encoding="utf-8",
    )
    stream = _stream()
    view = resolve_board_view(stream, _event(stream), studious_root=tmp_path)
    assert view.instruments[0].verdict_trail[0].outcome == "DONE"
