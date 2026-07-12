"""Building a BoardView from a gate-ledger epic ledger -- studious vocabulary in,
control-room's generic seven-state taxonomy out."""

from __future__ import annotations

import json
from pathlib import Path

from control_room.attention.models import AttentionState
from control_room.board.ledger import EpicLedger, StoryLedger, _slugify
from control_room.board.models import BoardSource
from control_room.board.protocol_adapter import build_protocol_board


def _epic(**stories: StoryLedger) -> EpicLedger:
    return EpicLedger(schema_version=1, slug="t1", status="running", stories=stories)


def test_landed_story_maps_to_done() -> None:
    epic = _epic(a=StoryLedger(status="landed", title="A"))
    view = build_protocol_board(epic, stream_id="s")
    assert view.instruments[0].state is AttentionState.DONE


def test_pending_story_maps_to_grinding_not_a_false_amber() -> None:
    epic = _epic(a=StoryLedger(status="pending", title="A"))
    view = build_protocol_board(epic, stream_id="s")
    assert view.instruments[0].state is AttentionState.GRINDING


def test_dropped_story_maps_to_done() -> None:
    epic = _epic(a=StoryLedger(status="dropped", title="A"))
    view = build_protocol_board(epic, stream_id="s")
    assert view.instruments[0].state is AttentionState.DONE


def test_unrecognized_status_degrades_to_grinding_never_a_guessed_amber() -> None:
    epic = _epic(a=StoryLedger(status="some-future-status-this-adapter-has-never-seen", title="A"))
    view = build_protocol_board(epic, stream_id="s")
    assert view.instruments[0].state is AttentionState.GRINDING


def test_parked_story_maps_to_parked_with_reason() -> None:
    epic = _epic(
        a=StoryLedger(status="parked", title="A", reason="acceptance: HOLD -- needs a call")
    )
    view = build_protocol_board(epic, stream_id="s")
    instrument = view.instruments[0]
    assert instrument.state is AttentionState.PARKED
    assert instrument.reason == "acceptance: HOLD -- needs a call"


def test_pending_story_names_its_unlanded_blocker() -> None:
    epic = _epic(
        a=StoryLedger(status="landed", title="A"),
        b=StoryLedger(status="pending", title="B", deps=("a", "c")),
        c=StoryLedger(status="pending", title="C"),
    )
    view = build_protocol_board(epic, stream_id="s")
    by_id = {i.id: i for i in view.instruments}
    assert by_id["b"].blocked_on == ("c",)  # "a" already landed -- not a blocker
    assert by_id["a"].blocked_on == ()
    assert by_id["c"].blocked_on == ()  # no deps of its own -- nothing blocks it


def test_pending_story_with_all_deps_landed_has_no_blocked_on() -> None:
    epic = _epic(
        a=StoryLedger(status="landed", title="A"),
        b=StoryLedger(status="pending", title="B", deps=("a",)),
    )
    view = build_protocol_board(epic, stream_id="s")
    by_id = {i.id: i for i in view.instruments}
    assert by_id["b"].blocked_on == ()


def test_fix_budget_reflects_worst_gate_retry_count() -> None:
    epic = _epic(
        a=StoryLedger(
            status="parked", title="A", reason="x: y", retries={"audit": 1, "acceptance": 2}
        )
    )
    view = build_protocol_board(epic, stream_id="s")
    assert view.instruments[0].fix_budget is not None
    assert view.instruments[0].fix_budget.used == 2


def test_no_retries_means_no_fix_budget() -> None:
    epic = _epic(a=StoryLedger(status="landed", title="A"))
    view = build_protocol_board(epic, stream_id="s")
    assert view.instruments[0].fix_budget is None


def test_resolution_command_only_present_when_parked() -> None:
    epic = _epic(
        a=StoryLedger(status="landed", title="A"),
        b=StoryLedger(status="parked", title="B", reason="acceptance: HOLD -- needs a call"),
    )
    view = build_protocol_board(epic, stream_id="s")
    by_id = {i.id: i for i in view.instruments}
    assert by_id["a"].resolution_command is None
    command = by_id["b"].resolution_command
    assert command is not None
    assert 'gate-ledger epic-story-set --epic "t1" --slug "b"' in command
    assert "--reset-retry acceptance" in command


def test_resolution_command_falls_back_to_gate_placeholder_without_colon() -> None:
    epic = _epic(a=StoryLedger(status="parked", title="A", reason="no colon here"))
    view = build_protocol_board(epic, stream_id="s")
    assert "--reset-retry <gate>" in view.instruments[0].resolution_command


def test_instruments_preserve_ledger_definition_order() -> None:
    """Instruments never move -- order matches the ledger's own dict order,
    never re-sorted by state."""
    epic = _epic(
        z=StoryLedger(status="landed", title="Z"),
        a=StoryLedger(status="parked", title="A", reason="x: y"),
        m=StoryLedger(status="pending", title="M"),
    )
    view = build_protocol_board(epic, stream_id="s")
    assert [i.id for i in view.instruments] == ["z", "a", "m"]


def test_cas_only_covers_m_and_r_bucket_states_severity_major() -> None:
    epic = _epic(
        grinding=StoryLedger(status="pending", title="Grinding"),
        parked=StoryLedger(status="parked", title="Parked", reason="acceptance: HOLD -- x"),
        landed=StoryLedger(status="landed", title="Landed"),
    )
    view = build_protocol_board(epic, stream_id="s")
    # Only the parked (M-bucket) story generates a CAS line -- grinding and
    # done/landed are silent by design.
    assert [m.instrument_id for m in view.cas] == ["parked"]


def test_board_source_is_protocol() -> None:
    epic = _epic(a=StoryLedger(status="landed", title="A"))
    view = build_protocol_board(epic, stream_id="s")
    assert view.source is BoardSource.PROTOCOL


# ---------------------------------------------------------------------------
# verdict_trail -- DESIGN.md's drawer content, gate-ledger's own work-log
# history, read via `control_room.board.ledger.load_work_history`.
# ---------------------------------------------------------------------------


def _write_work_history(
    studious_root: Path, epic_slug: str, story_slug: str, history: list
) -> None:
    work_dir = studious_root / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    filename = _slugify(f"{epic_slug}--{story_slug}")
    (work_dir / f"{filename}.json").write_text(
        json.dumps({"schemaVersion": 1, "slug": filename, "history": history}), encoding="utf-8"
    )


def test_verdict_trail_populated_from_the_stories_own_work_log(tmp_path: Path) -> None:
    _write_work_history(
        tmp_path,
        "t1",
        "a",
        [
            {"step": "build", "outcome": "DONE", "sha": "abc123"},
            {"step": "audit", "outcome": "PASS", "sha": "def456"},
        ],
    )
    epic = _epic(a=StoryLedger(status="landed", title="A"))
    view = build_protocol_board(epic, stream_id="s", studious_root=tmp_path)
    trail = view.instruments[0].verdict_trail
    assert [e.outcome for e in trail] == ["DONE", "PASS"]


def test_no_studious_root_means_no_verdict_trail(tmp_path: Path) -> None:
    """The default -- every existing caller/test that builds a board
    straight from an in-memory `EpicLedger` with no filesystem to read a
    work-log from keeps working unchanged."""
    epic = _epic(a=StoryLedger(status="landed", title="A"))
    view = build_protocol_board(epic, stream_id="s")
    assert view.instruments[0].verdict_trail == ()


def test_story_with_no_work_log_yet_has_an_empty_trail_not_a_crash(tmp_path: Path) -> None:
    epic = _epic(a=StoryLedger(status="pending", title="A"))
    view = build_protocol_board(epic, stream_id="s", studious_root=tmp_path)
    assert view.instruments[0].verdict_trail == ()


def test_each_storys_trail_is_looked_up_by_its_own_slug(tmp_path: Path) -> None:
    """Two stories in the same epic must never share a trail -- each reads
    its own `<epic>--<story>` work file."""
    _write_work_history(tmp_path, "t1", "a", [{"step": "build", "outcome": "DONE"}])
    _write_work_history(tmp_path, "t1", "b", [{"step": "build", "outcome": "FAILED"}])
    epic = _epic(
        a=StoryLedger(status="landed", title="A"), b=StoryLedger(status="pending", title="B")
    )
    view = build_protocol_board(epic, stream_id="s", studious_root=tmp_path)
    by_id = {i.id: i for i in view.instruments}
    assert by_id["a"].verdict_trail[0].outcome == "DONE"
    assert by_id["b"].verdict_trail[0].outcome == "FAILED"
