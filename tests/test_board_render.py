"""The one renderer -- never branches on BoardView.source, carries every v2 review item."""

from __future__ import annotations

from control_room.attention.models import AttentionState
from control_room.board.models import (
    BoardSource,
    BoardView,
    FixBudget,
    Instrument,
    VerdictTrailEntry,
)
from control_room.board.render import render_board

_RESOLUTION_COMMAND = 'gate-ledger epic-story-set --epic "t1" --slug "board-protocol-render"'


def _protocol_view(**overrides: object) -> BoardView:
    defaults: dict[str, object] = {
        "stream_id": "s1",
        "source": BoardSource.PROTOCOL,
        "instruments": (
            Instrument(
                id="board-protocol-render",
                label="Board-protocol render",
                state=AttentionState.PARKED,
                reason="acceptance: HOLD -- needs product signoff",
                blocked_on=("attention-detection",),
                fix_budget=FixBudget(used=1, cap=2),
                resolution_command=_RESOLUTION_COMMAND,
            ),
            Instrument(id="stream-discovery", label="Stream discovery", state=AttentionState.DONE),
        ),
    }
    defaults.update(overrides)
    return BoardView(**defaults)


def _generic_view(**overrides: object) -> BoardView:
    defaults: dict[str, object] = {
        "stream_id": "s2",
        "source": BoardSource.GENERIC,
        "instruments": (
            Instrument(
                id="interactive:abc",
                label="my-session",
                state=AttentionState.QUESTION_PENDING,
                reason="which approach?",
            ),
        ),
    }
    defaults.update(overrides)
    return BoardView(**defaults)


def test_master_caution_aria_pressed_reflects_acknowledged() -> None:
    view = _protocol_view()
    unacked = render_board(view, acknowledged=False)
    acked = render_board(view, acknowledged=True)
    assert 'aria-pressed="false"' in unacked
    assert 'aria-pressed="true"' in acked


def test_master_caution_blinks_only_when_unacknowledged_and_needed() -> None:
    view = _protocol_view()
    assert 'class="master-caution blink"' in render_board(view, acknowledged=False)
    assert 'class="master-caution blink"' not in render_board(view, acknowledged=True)
    assert 'class="master-caution"' in render_board(view, acknowledged=True)


def test_master_caution_never_blinks_for_review_ready_only() -> None:
    view = _protocol_view(
        instruments=(Instrument(id="a", label="A", state=AttentionState.REVIEW_READY),)
    )
    html = render_board(view, acknowledged=False)
    assert 'class="master-caution blink"' not in html
    assert 'class="master-caution"' in html


def test_fix_budget_wedges_rendered_filled_and_empty() -> None:
    html = render_board(_protocol_view())
    assert html.count('class="wedge wedge-filled"') == 1
    assert html.count('class="wedge wedge-empty"') == 1


def test_blocked_on_names_the_blocker() -> None:
    html = render_board(_protocol_view())
    assert "blocked on: attention-detection" in html


def test_lamp_form_uses_filled_and_hollow_glyphs() -> None:
    html = render_board(_protocol_view())
    assert "●" in html
    assert "○" in html


def test_aria_live_on_cas_list() -> None:
    view = _protocol_view()
    html = render_board(view)
    assert 'aria-live="polite"' in html


def test_reduced_motion_media_query_present() -> None:
    html = render_board(_protocol_view())
    assert "prefers-reduced-motion" in html


def test_instruments_render_in_view_order_never_resorted_by_state() -> None:
    """The parked (amber) instrument is listed first in the view -- even
    though `done` might seem like it should sort differently, render must
    preserve exactly the given order."""
    html = render_board(_protocol_view())
    parked_pos = html.index('data-instrument-id="board-protocol-render"')
    done_pos = html.index('data-instrument-id="stream-discovery"')
    assert parked_pos < done_pos


def test_resolution_command_rendered_as_code() -> None:
    html = render_board(_protocol_view())
    assert "<code>" in html
    assert "gate-ledger epic-story-set" in html


def test_degraded_banner_rendered_when_flagged() -> None:
    view = _generic_view()
    degraded = view.model_copy(
        update={"degraded_from_protocol": True, "degraded_reason": "schemaVersion 99 unsupported"}
    )
    html = render_board(degraded)
    assert "protocol-degraded" in html
    assert "schemaVersion 99 unsupported" in html


def test_no_degraded_banner_when_not_flagged() -> None:
    html = render_board(_generic_view())
    assert "protocol-degraded" not in html


def test_same_renderer_produces_analogous_structure_for_both_sources() -> None:
    """One schema, N adapters, no renderer branches: a protocol view and a
    generic view both produce the same structural shape (section, CAS list,
    instruments list) -- only field values differ, never which markup
    exists."""
    protocol_html = render_board(_protocol_view())
    generic_html = render_board(_generic_view())
    for fragment in (
        '<section class="board"',
        '<ol class="cas"',
        '<ol class="instruments">',
        "</section>",
    ):
        assert fragment in protocol_html
        assert fragment in generic_html


def test_html_is_escaped() -> None:
    view = _generic_view(
        instruments=(
            Instrument(
                id="x",
                label="<script>alert(1)</script>",
                state=AttentionState.GRINDING,
            ),
        )
    )
    html = render_board(view)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_generic_instrument_renders_without_fix_budget_or_blocked_on() -> None:
    html = render_board(_generic_view())
    assert "fix-budget" not in html
    assert "blocked-on" not in html


# ---------------------------------------------------------------------------
# The verdict-trail drawer -- DESIGN.md verbatim: "opened on demand, never
# ambient." A native <details>/<summary> disclosure, collapsed by default.
# ---------------------------------------------------------------------------


def test_verdict_trail_renders_as_a_collapsed_details_disclosure() -> None:
    view = _protocol_view(
        instruments=(
            Instrument(
                id="a",
                label="A",
                state=AttentionState.DONE,
                verdict_trail=(
                    VerdictTrailEntry(step="build", outcome="DONE", sha="abc123"),
                    VerdictTrailEntry(step="audit", outcome="PASS", sha="def456"),
                ),
            ),
        )
    )
    html = render_board(view)
    assert "<details" in html
    assert "<summary>Verdict trail</summary>" in html
    assert "abc123" in html
    assert "def456" in html
    assert html.index("DONE") < html.index("PASS")  # oldest first, never re-sorted


def test_no_verdict_trail_means_no_drawer_at_all() -> None:
    """Never an empty, ambient drawer -- absent entirely when there's
    nothing to show, matching every other optional instrument field here
    (fix-budget, blocked-on, resolution-command)."""
    html = render_board(_generic_view())
    assert "verdict-trail" not in html
    assert "<details" not in html


def test_verdict_trail_html_is_escaped() -> None:
    view = _protocol_view(
        instruments=(
            Instrument(
                id="a",
                label="A",
                state=AttentionState.DONE,
                verdict_trail=(VerdictTrailEntry(step="<script>", outcome="DONE"),),
            ),
        )
    )
    html = render_board(view)
    assert "<script>" not in html.split("<details", 1)[1]
    assert "&lt;script&gt;" in html
