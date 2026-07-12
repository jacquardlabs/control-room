"""The shared board schema: FixBudget wedges, the latched FIX lamp, the
amber-requires-reason invariant, and BoardView's master_caution rollup."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from control_room.attention.models import AttentionState
from control_room.board.models import BoardSource, BoardView, FixBudget, Instrument


def test_fix_budget_wedges_mark_consumed_slots() -> None:
    budget = FixBudget(used=1, cap=2)
    assert budget.wedges == (True, False)
    assert not budget.exhausted


def test_fix_budget_exhausted_past_cap() -> None:
    assert FixBudget(used=3, cap=2).exhausted


def test_fix_budget_zero_used_all_hollow() -> None:
    assert FixBudget(used=0, cap=2).wedges == (False, False)


def test_fix_lamp_latches_on_once_any_retry_recorded() -> None:
    """Latched, not current-state: a landed (done) instrument with a nonzero
    fix budget still shows the FIX lamp on -- design-history.md's "latched
    FIX lamps carrying history without a timeline.\""""
    instrument = Instrument(
        id="story-a", label="Story A", state=AttentionState.DONE, fix_budget=FixBudget(used=1)
    )
    assert instrument.fix_lamp_on


def test_fix_lamp_off_with_no_fix_budget() -> None:
    instrument = Instrument(id="story-a", label="Story A", state=AttentionState.DONE)
    assert not instrument.fix_lamp_on


def test_amber_instrument_without_reason_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Instrument(id="story-a", label="Story A", state=AttentionState.PARKED)


def test_amber_instrument_with_blank_reason_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Instrument(id="story-a", label="Story A", state=AttentionState.PARKED, reason="   ")


def test_amber_instrument_with_reason_is_accepted() -> None:
    instrument = Instrument(
        id="story-a", label="Story A", state=AttentionState.PARKED, reason="acceptance: HOLD"
    )
    assert instrument.reason == "acceptance: HOLD"


def test_died_instrument_needs_no_reason() -> None:
    """`died` is red, not amber -- the amber invariant doesn't apply to it."""
    Instrument(id="story-a", label="Story A", state=AttentionState.DIED)


def test_board_view_master_caution_true_only_for_m_bucket() -> None:
    parked = Instrument(
        id="a", label="A", state=AttentionState.PARKED, reason="acceptance: HOLD -- needs a call"
    )
    review = Instrument(id="b", label="B", state=AttentionState.REVIEW_READY)
    view_with_m = BoardView(
        stream_id="s", source=BoardSource.PROTOCOL, instruments=(parked, review)
    )
    assert view_with_m.master_caution

    view_without_m = BoardView(stream_id="s", source=BoardSource.PROTOCOL, instruments=(review,))
    assert not view_without_m.master_caution
