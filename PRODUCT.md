# Product context

> **Confidence note:** pre-implementation (design and backlog only — no code). Drawn
> from the founding note (`docs/founding-note.md`, 2026-07-07), the board design work
> it grew out of (`docs/design-history.md`), and the owner's stated vision, verbatim
> where possible. Treat as **high confidence on intent, medium on mechanics** —
> attention-detection heuristics and input-back reachability are unproven until T1/T2.
> Re-run `/extract-product-context` once code exists.

## Why this product exists

Agentic development made concurrent work normal: on an ordinary day the owner runs a
product build across five worktrees, an epic driver, background research agents, and
an interactive session simultaneously — observable only as separate task counts and
scrollback. The existing category (herdr, Orca, Conductor) answers this with terminal
multiplexing: panes of streaming agent logs. That is the wrong information design for
the operator's two real questions: **is each stream progressing, and what needs me
right now?**

control-room is the answer designed from those questions: a fleet of instruments, not
a wall of text. Progress renders as gauges (the Flight Deck board, which won a timed
comprehension test against three denser designs); attention renders as a needs-you
queue and a MASTER CAUTION you can acknowledge; logs exist one deliberate click away,
never ambient.

## Who uses it

### Primary persona

The owner-operator running multiple Claude Code work streams daily — epics via
`/work-through`, winnow-style product builds in parallel worktrees, background
research fleets, interactive sessions — who currently discovers "it needed me an hour
ago" by going tab to tab. They keep control-room open on a second monitor; it earns
that spot only if it surfaces needs-you moments faster than the harness's own
notifications. That bar is written into T1's exit gate.

### Secondary persona

None by design through T3. Multi-user, team dashboards, or hosted anything is a
different product's constitution.

## Product principles

1. **Progress and attention, not logs.** The founding opinion and the moat. Every
   design temptation to add an ambient log pane is refused; the drawer is the only
   home for detail, and it opens on demand.
2. **Blink is reserved.** Exactly one motion channel means "a human is needed" —
   inherited from the board, enforced everywhere.
3. **Instruments never move.** Position is identity; scale is a clustering problem,
   never a reordering one.
4. **Read-only until amended.** Through T1 the tool observes disk truth and renders
   it; it writes nothing but its own local ack/preferences state. The T2 crossing
   (operator actions through the surface) happens by written PRODUCT.md amendment
   before any control code lands.
5. **The operator acts; the tool never does.** Even after T2, control-room executes
   only explicit human actions and logs each one — no auto-answer, no auto-retry, no
   policy. The needs-you queue is a to-me list, not a to-do engine.
6. **Local and keyless.** The user's transcripts stay on the user's machine; no
   hosted service, no telemetry.
7. **Wraps whatever workflow.** Streams are generic (any session, any Workflow run,
   any background task); semantics arrive by protocol (board events), never by
   hardcoding studious-isms. The attention taxonomy is generic vocabulary.

## Feature tracker

Issues: [GitHub](https://github.com/jacquardlabs/control-room/issues), organized under
the T1/T2/T3 milestones. Capability summary:

| Capability | Milestone | Status |
|---|---|---|
| Stream discovery (sessions, workflow runs, background tasks) | T1 | Not started |
| Generic attention detection (needs-you taxonomy) | T1 | Not started |
| Board-protocol enrichment (epics show parks/verdicts/budgets) | T1 | Not started |
| Fleet strip + tabs + SSE shell (viva-pattern local server) | T1 | Not started |
| Flight Deck renderer adoption (from studious #98) | T1 | Not started |
| Notifications + acknowledge loop | T1 | Not started |
| Per-stream cost vitals | T1 | Not started |
| Read-only crossing amendment, then: resolve parks, answer questions, action log | T2 | Not started |
| Launch epics/workflows/sessions from the app; presets; worktree lifecycle | T3 | Not started |

## Critical user journeys

1. **The glance:** second monitor, fleet strip — 6 grinding, 2 need you, caution
   blinking (2) > open the amber tab > park reason and resolution command in the
   drawer > act in the terminal (T1) or from the chair (T2) > acknowledge > blink
   stops, record stays.
2. **The interrupt done right:** deep in other work > one notification: "auth-refresh
   parked — NEEDS DISCUSSION" > decide in ten seconds whether it can wait > it usually
   can, *and now that's a decision instead of an anxiety*.
3. **The full loop (T3):** kick off an epic from a preset > watch it as a tab >
   answer its one park from the chair > hand the finished branch to `gh pr create`.

## What we're NOT building

- **A log multiplexer** — no ambient terminal panes, ever. That's herdr/Orca's lane
  and the founding anti-pattern.
- **The per-epic board** — ships in studious (#98); control-room adopts its renderer
  and schema rather than forking them.
- **Session analytics/diagnosis** — cctx's job, retrospective. Shared parsing code is
  a library decision, never a product merge (settled 2026-07-07).
- **Autonomy of any kind** — no auto-answering questions, no auto-approving
  permissions, no policy engine, no retry logic. Verdicts belong to gates; actions
  belong to the human.
- **Hosted, multi-user, telemetered anything.**

## Current known problems

1. **Vendor blast radius peaks at T3.** An all-in-one operator platform sits directly
   in the path of Anthropic's desktop/`/workflows`/Agent-HQ evolution. Standing rule:
   a written vendor-landscape re-check gates T3 entry, and this file gets re-read
   against each major Anthropic surface release. Defenses: local-first, workflow-
   agnostic, the attention-first opinion, protocol enrichment.
2. **Attention detection is heuristic** for non-cooperating streams (transcript-tail
   inference of input-blocked/question-pending). False needs-you is the product-
   killing failure mode — the taxonomy degrades to "grinding" on uncertainty, never
   to a false alarm. Fixtures required per state before T1 exit.
3. **Input-back reachability is unproven** for plain interactive sessions;
   permission prompts may be vendor-gated. T2 carries an explicit investigation story
   whose honest outcome may be "not reachable without vendor support."
4. **The renderer/schema dependency runs through studious #98** — by design. If #98
   stalls, T1's entry gate holds control-room too; that coupling is accepted and
   recorded rather than worked around by forking.

## Business model

None yet. Same posture as the portfolio: local-first, the user's own subscription; if
it ever earns more than owner use, monetization is decided by written amendment. The
plausible long shape (an individual operator-seat license beside winnow's reviewer
seat) is noted for the record, not planned.
