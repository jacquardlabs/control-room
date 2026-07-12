"""The one renderer: a `BoardView` in, a self-contained HTML fragment out.

Never branches on `BoardView.source` -- a protocol-enriched view and a
generic-vitals view walk the exact same code below, differing only in which
fields are populated (`fix_budget`, `blocked_on`, `resolution_command` are
`None`/empty on a generic instrument, present on a protocol one). That's
"one schema, N adapters, no renderer branches," verbatim.

Carries every "v2 review item" the story's acceptance criteria names,
each traceable to `docs/design-history.md`'s Flight Deck v2 pass:

- **MASTER CAUTION aria-pressed** -- a real toggle button; `acknowledged`
  sets both the attribute and the class that stops the blink.
- **Fix-budget wedges** -- one `<span>` per `FixBudget.wedges` slot.
- **Blocked-instrument naming** -- `blocked_on` renders as prose naming the
  blocker(s), never just a count.
- **Lamp form** -- `●`/`○`, never a color-only signal.
- **aria-live CAS** -- the alerting list is `aria-live="polite"`.
- **Reduced-motion** -- an embedded media query kills the blink animation
  but keeps a solid, still-legible amber field, per DESIGN.md's "reduced-
  motion keeps meaning."
- **Instruments never move** -- rendered in `view.instruments`' own order
  (each adapter's definition order), never re-sorted by state here.

Fragment-level, not a full page: `fleet-shell` (issue #4) owns the
committed self-contained page this embeds into, its CSS custom properties,
and the SSE wiring that re-renders it. This function has no page chrome of
its own beyond the one embedded `<style>` block the reduced-motion rule
needs to be self-contained without fleet-shell's stylesheet.
"""

from __future__ import annotations

from html import escape

from control_room.board.bucket import WallBucket, wall_bucket
from control_room.board.models import (
    BoardView,
    CasMessage,
    FixBudget,
    Instrument,
    VerdictTrailEntry,
)

_REDUCED_MOTION_STYLE = (
    "<style>@media (prefers-reduced-motion: reduce) {"
    " .master-caution.blink { animation: none; background: var(--amber-solid, #b45309); }"
    " }</style>"
)


def render_board(view: BoardView, *, acknowledged: bool = False) -> str:
    """Render one `BoardView` to a self-contained HTML fragment."""
    caution_blink = view.master_caution and not acknowledged
    degraded_attr = _bool_attr(view.degraded_from_protocol)
    parts = [
        f'<section class="board" data-stream-id="{escape(view.stream_id)}" '
        f'data-source="{view.source.value}" data-degraded="{degraded_attr}">',
    ]
    if view.degraded_from_protocol:
        parts.append(
            '<p class="protocol-degraded" role="status">'
            "board protocol unavailable -- showing generic vitals"
            + (f": {escape(view.degraded_reason)}" if view.degraded_reason else "")
            + "</p>"
        )
    parts.append(_render_master_caution(view, acknowledged=acknowledged, blink=caution_blink))
    parts.append(_render_cas(view))
    parts.append('<ol class="instruments">')
    parts.extend(_render_instrument(i) for i in view.instruments)
    parts.append("</ol>")
    parts.append(_REDUCED_MOTION_STYLE)
    parts.append("</section>")
    return "".join(parts)


def _render_master_caution(view: BoardView, *, acknowledged: bool, blink: bool) -> str:
    needs_you_count = sum(1 for i in view.instruments if wall_bucket(i.state) is WallBucket.M)
    classes = "master-caution" + (" blink" if blink else "")
    label = f"MASTER CAUTION -- {needs_you_count} need you" if needs_you_count else "MASTER CAUTION"
    return (
        f'<button type="button" class="{classes}" aria-pressed="{_bool_attr(acknowledged)}" '
        f'aria-label="{escape(label)}" data-needs-you-count="{needs_you_count}">'
        "MASTER CAUTION</button>"
    )


def _render_cas(view: BoardView) -> str:
    lines = "".join(_render_cas_line(m) for m in view.cas)
    return f'<ol class="cas" aria-live="polite">{lines}</ol>'


def _render_cas_line(message: CasMessage) -> str:
    bucket = wall_bucket(message.state)
    bucket_class = bucket.value if bucket else "none"
    instrument_id = escape(message.instrument_id)
    return (
        f'<li class="cas-line cas-{bucket_class}" data-instrument-id="{instrument_id}">'
        f"{escape(message.text)}</li>"
    )


def _render_instrument(instrument: Instrument) -> str:
    bucket = wall_bucket(instrument.state)
    attn_lamp_on = bucket is WallBucket.M
    fix_glyph = _lamp_glyph(instrument.fix_lamp_on)
    parts = [
        f'<li class="instrument state-{instrument.state.value}" '
        f'data-instrument-id="{escape(instrument.id)}" data-state="{instrument.state.value}">',
        f'<span class="lamp lamp-attn" aria-hidden="true">{_lamp_glyph(attn_lamp_on)}</span>',
        f'<span class="lamp lamp-fix" aria-hidden="true">FIX {fix_glyph}</span>',
        f'<span class="label">{escape(instrument.label)}</span>',
        f'<span class="state-text">{escape(instrument.state.value)}</span>',
    ]
    if instrument.reason:
        parts.append(f'<p class="reason">{escape(instrument.reason)}</p>')
    if instrument.fix_budget is not None:
        parts.append(_render_fix_budget(instrument.fix_budget))
    if instrument.blocked_on:
        blockers = ", ".join(escape(b) for b in instrument.blocked_on)
        parts.append(f'<p class="blocked-on">blocked on: {blockers}</p>')
    if instrument.resolution_command:
        command = escape(instrument.resolution_command)
        parts.append(f'<p class="resolution-command"><code>{command}</code></p>')
    if instrument.verdict_trail:
        parts.append(_render_verdict_trail(instrument.verdict_trail))
    parts.append("</li>")
    return "".join(parts)


def _render_verdict_trail(trail: tuple[VerdictTrailEntry, ...]) -> str:
    """DESIGN.md's drawer, verbatim: "opened on demand, never ambient." A
    native `<details>`/`<summary>` disclosure -- collapsed by default,
    keyboard-operable, no JS required to open/close it."""
    rows = "".join(_render_verdict_trail_row(entry) for entry in trail)
    return (
        '<details class="verdict-trail">'
        "<summary>Verdict trail</summary>"
        f'<ol class="verdict-trail-rows">{rows}</ol>'
        "</details>"
    )


def _render_verdict_trail_row(entry: VerdictTrailEntry) -> str:
    sha = f'<span class="vt-sha">{escape(entry.sha)}</span>' if entry.sha else ""
    return (
        "<li>"
        f'<span class="vt-step">{escape(entry.step)}</span>'
        f'<span class="vt-outcome">{escape(entry.outcome)}</span>'
        f"{sha}"
        "</li>"
    )


def _render_fix_budget(budget: FixBudget) -> str:
    wedges = "".join(_render_wedge(filled) for filled in budget.wedges)
    return (
        f'<div class="fix-budget" data-used="{budget.used}" data-cap="{budget.cap}">{wedges}</div>'
    )


def _render_wedge(filled: bool) -> str:
    css_class = "wedge-filled" if filled else "wedge-empty"
    return f'<span class="wedge {css_class}" aria-hidden="true"></span>'


def _lamp_glyph(on: bool) -> str:
    return "●" if on else "○"


def _bool_attr(value: bool) -> str:
    return "true" if value else "false"
