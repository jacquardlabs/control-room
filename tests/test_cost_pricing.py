"""`control_room.cost.pricing`: exact-match rates, family-substring fallback,
and the "no fabricated number" refusal for a wholly unrecognized model id.
"""

from __future__ import annotations

from control_room.cost.pricing import lookup_rates


def test_exact_match_returns_the_documented_opus_4_5_rates():
    rates = lookup_rates("claude-opus-4-5-20251101")
    assert rates is not None
    assert rates.input == 5 / 1_000_000
    assert rates.output == 25 / 1_000_000
    assert rates.cache_write == rates.input * 1.25
    assert rates.cache_read == rates.input * 0.1


def test_unrecognized_but_sonnet_family_model_falls_back_to_sonnet_tier():
    rates = lookup_rates("claude-sonnet-9000-hypothetical")
    assert rates is not None
    assert rates.input == 3 / 1_000_000
    assert rates.output == 15 / 1_000_000


def test_unrecognized_but_haiku_family_model_falls_back_to_haiku_tier():
    rates = lookup_rates("claude-haiku-9000")
    assert rates is not None
    assert rates.input == 1 / 1_000_000


def test_family_match_is_case_insensitive():
    assert lookup_rates("CLAUDE-OPUS-9000") is not None


def test_wholly_unrecognized_model_returns_none_not_a_guess():
    assert lookup_rates("some-other-vendors-model") is None
    assert lookup_rates("<synthetic>") is None
