"""Per-token USD rates for Claude models -- the local, keyless pricing source
`control_room.cost.usage` prices a stream's transcript usage against.

**Not fetched from a hosted pricing service.** PRODUCT.md principle 6 ("local
and keyless") and the design doc's operational-readiness section both frame
control-room as making no outbound calls of its own; a live fetch of a
pricing table on every poll tick (or even once at startup) would be exactly
that kind of hosted-service dependency, for data that changes on the order of
months, not seconds. Instead this is a small, committed, versioned table --
the same shape of tradeoff already accepted for `control_room.vendor.
cctx_discovery` (a tracked copy, manually re-synced, drift is a named risk
rather than a silent one).

**Source & date:** Anthropic's published per-model pricing
(anthropic.com/pricing), read while building this story, 2026-07. Four rates
per model, USD per token (the table below states them per-million-token for
human readability, converted to per-token in `RATES`):

- `input` -- a normal (cache-miss) input token.
- `output` -- a generated output token.
- `cache_write` -- writing a prompt-cache entry (5-minute TTL), consistently
  1.25x the model's own `input` rate across every generation checked.
- `cache_read` -- a prompt-cache hit, consistently 0.1x `input`.

**Known limitation, named rather than hidden:** a model id newer than this
table (a generation released after this story was built) falls back to
`FAMILY_FALLBACK_RATES`, keyed on a substring match against "opus" /
"sonnet" / "haiku" -- the three tiers Anthropic's pricing has consistently
used across generations. That fallback is a best-effort approximation, not a
guarantee: a real pricing change within a family (as Opus 4 -> Opus 4.5's
5x price cut shows happens) will silently under- or over-price a brand-new
model until this table is hand-updated. Re-sync cadence is the same open
question already named for the cctx vendoring copy -- not solved here, just
not hidden. A model id that doesn't even substring-match a known family
(true novel naming) has no fallback at all: `lookup_rates` returns `None`,
and callers must not fabricate a number for it (mirrors `control_room.wall`'s
"a fabricated $0.00 would silently claim a real, measured zero spend").
"""

from __future__ import annotations

from typing import NamedTuple


class ModelRates(NamedTuple):
    """USD per token -- already divided down from the per-million figures
    Anthropic publishes, so `usage.py` never repeats that arithmetic."""

    input: float
    output: float
    cache_write: float
    cache_read: float


def _tier(input_per_mtok: float, output_per_mtok: float) -> ModelRates:
    """Every checked generation prices cache_write at 1.25x input and
    cache_read at 0.1x input -- build a tier from the two headline numbers
    Anthropic actually publishes, rather than restating all four by hand
    per row (a transposition typo in a hand-copied `cache_write` figure
    would be easy to miss on review; deriving it can't drift from `input`)."""
    input_rate = input_per_mtok / 1_000_000
    return ModelRates(
        input=input_rate,
        output=output_per_mtok / 1_000_000,
        cache_write=input_rate * 1.25,
        cache_read=input_rate * 0.1,
    )


# Exact model-id matches, newest/cheapest-per-tier first for readability.
# Keys are the literal `message.model` strings Claude Code writes to a
# transcript -- both the dated form (e.g. "claude-opus-4-5-20251101") and a
# short alias, since either has been observed in real transcripts.
RATES: dict[str, ModelRates] = {
    # Opus tier
    "claude-opus-4-5-20251101": _tier(5, 25),
    "claude-opus-4-5": _tier(5, 25),
    "claude-opus-4-1-20250805": _tier(15, 75),
    "claude-opus-4-1": _tier(15, 75),
    "claude-opus-4-20250514": _tier(15, 75),
    "claude-opus-4": _tier(15, 75),
    # Sonnet tier
    "claude-sonnet-4-5-20250929": _tier(3, 15),
    "claude-sonnet-4-5": _tier(3, 15),
    "claude-sonnet-4-20250514": _tier(3, 15),
    "claude-sonnet-4": _tier(3, 15),
    "claude-3-7-sonnet-20250219": _tier(3, 15),
    "claude-3-5-sonnet-20241022": _tier(3, 15),
    # Haiku tier
    "claude-haiku-4-5-20251001": _tier(1, 5),
    "claude-haiku-4-5": _tier(1, 5),
    "claude-3-5-haiku-20241022": _tier(0.80, 4),
    "claude-3-haiku-20240307": _tier(0.25, 1.25),
}

# Best-effort default per family, for a model id newer than `RATES` above --
# see the module docstring's "known limitation" for what this trades away.
# Ordered so the first substring match wins; "opus"/"sonnet"/"haiku" never
# overlap in a real model id, so order only matters for readability here.
FAMILY_FALLBACK_RATES: tuple[tuple[str, ModelRates], ...] = (
    ("opus", _tier(5, 25)),
    ("sonnet", _tier(3, 15)),
    ("haiku", _tier(1, 5)),
)


def lookup_rates(model: str) -> ModelRates | None:
    """Exact match first, then a family-substring best-effort fallback,
    else `None` -- never a fabricated number for a wholly unrecognized
    model id (see module docstring)."""
    if exact := RATES.get(model):
        return exact
    lowered = model.lower()
    for family, rates in FAMILY_FALLBACK_RATES:
        if family in lowered:
            return rates
    return None
