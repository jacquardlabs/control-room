# Design system

> Pre-implementation: founding intent, inherited from the board design work
> (`docs/design-history.md` — concepts → riffs → timed comprehension test → Flight
> Deck v2). Re-run `/extract-design-system` once real surfaces exist.

## Surfaces

- **The wall (fleet strip)** — always visible: N grinding · R review-ready · M need
  you · MASTER CAUTION with unacknowledged count · aggregate burn. The condensed
  control-room. `review-ready` counts separately from `grinding` so a finished-and-
  waiting stream is never mistaken for a still-working one; MASTER CAUTION blinks for
  M only, never R (settled 2026-07-11, see the T1 design doc's gate-design-review
  revision, `docs/specs/2026-07-11-t1-design.md`).
- **Stream tabs** — one per session/workflow/task; tab label carries the stream's
  attention glyph so the strip and tabs never disagree.
- **The board (per tab)** — control-room's own schema-driven renderer for
  board-protocol streams (schema adopted from studious #98, pixels are control-room's
  own — settled 2026-07-11, see founding-note.md's addendum 3): instruments,
  annunciator lamps, severity-ordered CAS, verdict-trail drawer.
- **Notifications** — OS-level, fired only on attention-state *changes*, silenced by
  acknowledge, never repeated without a new event.
- **Action log (T2+)** — append-only render of every operator action taken through
  the surface.

## Semantic palette

### States (the attention taxonomy — generic vocabulary, no studious-isms)

- **grinding** — neutral/blue; working, nothing needed. The default and the majority.
- **input-blocked** — amber; a permission prompt or tool approval is waiting.
- **question-pending** — amber; the stream asked the human something.
- **parked** — amber; a judgment verdict or exhausted budget (via board protocol).
- **review-ready** — white/advisory; finished output awaiting human eyes.
- **died** — red; process/agent ended abnormally. The only red.
- **done** — green; terminal and healthy.
- Uncertainty degrades to **grinding**, never to a false amber.

### Per-surface rendering

Same state words everywhere — strip glyphs, tab badges, CAS lines, aria-labels. Amber
classes always carry their reason text; an amber without a reason is a rendering bug.

## Vocabulary

stream, the wall, board, attention event, needs-you queue, MASTER CAUTION,
acknowledge (ack), drawer, action log. One name per concept across UI, schema keys,
notifications, and docs.

## Formatting

- The wall leads every layout; "Needs you" content precedes all progress content.
- CAS ordering is severity-major (amber > white > green), recency within class.
- Numerals tabular; burn always with units against context ("$4.20 today").
- Blink is reserved for unacknowledged needs-you — nothing else moves repeatedly.

## Per-surface conventions

### Web (the app)

- Local server, viva-pattern: stdlib, SSE, self-contained committed page, no CDN.
- Read-only render of disk truth: kill and restart the server mid-anything and the
  screen reconstructs exactly (no server-held state beyond ack/preferences).
- Instruments never move; new streams append, dead streams gray then age out visibly.
- Gauges and caution are real buttons: focus rings, aria-labels, `aria-live` CAS,
  reduced-motion keeps meaning (solid amber field when blink dies).
- Logs and transcripts render only inside the drawer, on demand.

### Notifications

- One per state *change*; body names the stream, the state, and the one-clause
  reason; acknowledged streams stay silent until a new event.

## Anti-patterns (do NOT do these)

- Ambient log panes or streaming text anywhere outside the drawer — the founding
  refusal; if it scrolls by itself, it doesn't ship.
- Reordering instruments by status (position is identity).
- A needs-you signal without its reason and, where one exists, its resolution command.
- Blink for anything other than "a human is needed."
- Softening `died` or dramatizing `parked` — parked is amber and normal; the cord
  working is not an emergency.
- Auto-anything: answering, approving, retrying, dismissing. The tool renders and
  (post-T2) relays explicit human acts — nothing else.
