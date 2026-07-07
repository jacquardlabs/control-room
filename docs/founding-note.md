# control-room — founding note (2026-07-07)

> Name: **control-room** (owner-chosen, 2026-07-07) — where you sit and watch the gauges
> and screens to see what's going on. Continuity with the board (Flight Deck instruments
> feed the room's wall of screens), and the room's actual job is the product's: many
> operations, one operator, intervene by exception.
>
> Naming note: "Control Room" was also the working title of the dense per-epic board
> *skin* that lost the comprehension test to Flight Deck. Disambiguation is clean:
> **control-room is the fleet product; Flight Deck is the winning per-stream board
> style rendered inside it.**

## The vision, in the owner's words (paraphrased tight)

A tabbed dashboard across sessions and work streams that churns away giving updates and
says when input is needed. herdr/Orca/Conductor lean on *inputs and logs streaming by* —
the need is the opposite information design: **see workflow progress, know when to act.**
Eventually: workflow kick-off and input-back-to-the-agent from the app — an all-in-one
operator platform wrapping *whatever* workflow.

## Why this is different from what exists

- **herdr/Orca/Conductor**: PTY multiplexers — panes of scrolling agent terminals. They
  answer "what is it typing"; control-room answers "is it progressing and does it need me."
  The comprehension test that picked Flight Deck is the evidence for this information
  design: abstracting the log away *won*.
- **The harness** (`/workflows`, task notifications, the coming desktop surfaces): per-run,
  per-session, vendor-paced. Control-room is cross-everything (sessions, Workflow runs,
  background tasks, multiple repos/worktrees), attention-first, and opinionated about
  what may interrupt.
- **cctx**: analyst-after ("what happened, what did it cost, patch CLAUDE.md"). Control-room is
  operator-during. Shared substrate (JSONL parsing) = shared library, never a merged
  product — settled 2026-07-07.
- **The studious board (#98)**: one epic, deep semantics. Control-room is the fleet above it —
  boards are what its tabs *open into* when a stream is a studious epic.

## Architecture (three layers, all previously de-risked)

1. **Capture** — transcript/journal tailing (cctx-proven tech), waiting-state detection
   (permission prompts, pending questions, finished tasks, died agents — the harness
   knows these, nobody aggregates them), optional hook streaming, optional OTel.
2. **Model** — streams (a stream = session | workflow run | background task | board-
   protocol emitter), each with: progress (phases where they exist), attention state
   (the needs-you taxonomy: input-blocked · question-pending · parked · review-ready ·
   died · done · grinding), cost. **The attention event schema is defined once, in the
   board work (#98), as a taxonomy — not a studious-ism.** Control-room is its second consumer;
   gauntlet runs its third. That kills the one-emitter spec-graveyard risk.
3. **Render** — the schema-driven Flight Deck renderer (proven across 4 boards on one
   state shape). Tabs per stream; a fleet strip (the wall of screens, condensed) always visible:
   N grinding · M need you · MASTER CAUTION with count; per-tab, the board (semantic
   streams) or generic vitals (plain streams).

## The staged path (each stage independently useful; each gated)

- **T0 — the board ships first** (studious #98, behind the WIP cap). Hardens renderer +
  attention schema on real epics. Control-room work before T0 is premature by construction.
- **T1 — read-only control-room**: fleet tab strip + needs-you queue + per-stream tabs, local
  server, transcript/journal tailing. Notifications: local (and the harness's push
  hook path) when attention state changes. Strictly observe-only. This alone is "the
  tool I've been looking for" as stated.
- **T2 — input-back**: answer a parked story, a pending question, a permission decision
  *from the app*. The mechanic already exists in-house: viva's browser→file→session
  loop and work-through's park/resolution commands are exactly this plumbing,
  generalized. Constitutional note: input-back is the human acting through a surface —
  it does not breach recommend-only, but it DOES end read-only; that boundary gets
  crossed deliberately, in writing, at T2 and not before.
- **T3 — kick-off**: start work from the app — named workflows, `/work-through` epics,
  headless sessions in worktrees. This is the "all-in-one platform wrapping whatever
  workflow" step, and it's where control-room becomes an *operator seat* rather than a
  monitor. Brigade's mission-control section (now studious's initiative-altitude doc)
  described this seat; control-room generalizes it beyond initiatives.

## Tensions, named now so they don't ambush later

1. **Vendor blast radius is maximal at T3.** An all-in-one wrapper is the most exposed
   position in the portfolio. Defenses: local-first/keyless (constitutional), workflow-
   agnostic (wraps vendor surfaces rather than competing per-run), attention-first
   opinion (the thing generic vendor views won't commit to), protocol enrichment.
   Standing rule: re-check this note against each Anthropic desktop/Agent-HQ release.
2. **Scope gravity.** Every stage will tempt log panes back in ("just show me the
   tail"). The founding opinion is the moat: progress and attention, logs one
   deliberate click away (drawer), never ambient.
3. **Boundary rule scoring**: audience = any Claude Code user with concurrent work
   (independent of studious ✓), job distinct from cctx/winnow/studious ✓ → separate
   repo *when built*. Dormancy discipline applies (brigade precedent): no repo until
   T1 starts; this note is the design record.
4. **Not the WIP cap's problem yet.** Queue: winnow phase-0 · work-through re-impl ·
   wright v0 → board (#98) → control-room T1.

## One-line identity

cctx tells you what your agents did wrong last week; the board tells you what your epic
needs right now; **the control-room tells you which of your eight Claudes is allowed to
interrupt you — and, eventually, lets you answer from the chair.**

---

## Addendum — 2026-07-07 (same day, later)

The dormancy line above ("no repo until T1 starts") is superseded by owner decision:
this repo stands up now as the **design and backlog home** — founding note, PRODUCT.md,
and the T1/T2/T3 milestones with their stories. The build order is unchanged: T1 work
begins only after its entry gate (studious #98 board shipped, attention schema hardened
on a real epic) and behind the standing WIP cap. A repo with issues is a promise to
*decide well later*, not to build now — the brigade precedent, applied with its lesson.

## Addendum 2 — 2026-07-07: T4, the desktop appliance

Owner addition: at some point control-room becomes a **desktop app using the Claude
credentialing process** — winnow's Phase-4 pattern applied here: Tauri-class shell,
signing/notarization, and Agent SDK auth on the user's own subscription with a
first-run auth doctor. Recorded as the T4 milestone; gated on T1's daily-driver
verdict holding (a desktop appliance is only earned by a tool already kept open), and
unordered relative to T2/T3. Through T3 control-room needs no credentials of its own —
the monitor reads disk and launched sessions inherit the user's Claude Code auth.
