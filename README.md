# control-room

The operator seat for concurrent Claude Code work, from [Jacquard Labs](https://github.com/jacquardlabs).

> [!NOTE]
> Design and backlog repo — no code yet. Build begins at T1's entry gate (the studious
> andon board shipped and its attention schema hardened on a real epic), behind the
> portfolio WIP cap. See [The staged path](#the-staged-path).

Where you sit and watch the gauges and screens to see what's going on: a tabbed dashboard across
every session, workflow run, and background task on your machine, churning away giving updates and
telling you when your input is needed. One fleet strip always visible (N grinding · M need you ·
MASTER CAUTION), one tab per work stream, the winning Flight Deck board rendering each stream's
progress.

The founding opinion, and the moat: **progress and attention, not logs.** herdr, Orca, and Conductor
multiplex agent terminals — panes of text streaming by, answering "what is it typing." control-room
answers the operator's actual questions: *is it progressing, and which of my eight Claudes is
allowed to interrupt me?* Logs live one deliberate click away, in a drawer, never ambient. This
information design won a timed comprehension test against three denser alternatives before it was
chosen.

## What control-room must never become

Not a log multiplexer or terminal-pane manager. Not hosted, not multi-user, not telemetered. Not a
policy engine — it never answers, approves, or retries anything on its own; through T1 it is
strictly read-only, and the T2 crossing into operator actions happens by written constitutional
amendment, not drift. Not the per-epic board itself (that ships inside
[studious](https://github.com/jacquardlabs/studious), issue #98) and not session analytics (that's
[cctx](https://github.com/jacquardlabs/cctx)'s job, after the fact).

## The staged path

| Stage | Delivers | Entry gate |
|---|---|---|
| T0 | studious andon board (studious #98) hardens the schema-driven renderer and attention-event taxonomy on real epics | — |
| T1 — read-only | stream discovery, generic attention detection (input-blocked · question-pending · review-ready · died · grinding), board-protocol enrichment, tabs + fleet strip, notifications with an acknowledge loop | studious #98 board shipped; attention schema hardened on ≥1 real epic |
| T2 — input-back | resolve a parked story, answer a pending question, from the app, with an honest action log | T1 exit held; a written PRODUCT.md amendment merged first |
| T3 — kick-off | launch epics, workflows, and headless sessions from the chair | T2 exit; a written vendor-landscape re-check |
| T4 — desktop appliance | packaged desktop app (Tauri-class shell, winnow's Phase-4 packaging pattern) with Claude credentialing via the Agent SDK | T1 exit verdict holding |

Full gate language and exit criteria live in the repo's milestones and
[`docs/founding-note.md`](docs/founding-note.md).

## Install

> TODO: nothing to install — this is a design and backlog repo, no code yet. Revisit once T1 opens.

## Usage

> TODO: no usage yet, same reason as Install.

## Documentation

- [`docs/founding-note.md`](docs/founding-note.md) — the full vision and its named tensions.
- [`docs/design-history.md`](docs/design-history.md) — how the Flight Deck board design was chosen.
- [`PRODUCT.md`](PRODUCT.md) — personas, principles, the NOT-building list, known problems.
- [`DESIGN.md`](DESIGN.md) — the attention taxonomy, surface conventions, anti-patterns.

## Contributing

Spec → plan → build. Design specs land in `docs/specs/`, plans in `docs/plans/`, both dated. Every
proposal is read against `PRODUCT.md` and `DESIGN.md` first — backlog grooming, spec work, and
design-doc drafting are in scope now; code is not, until T1 opens.

Quality gates run once there's code to gate:

| Gate | When | Command |
|---|---|---|
| Should we build? | Before any engineering | `/gate-should-we-build [idea]` |
| Design review | After a design doc, before implementation | `/gate-design-review` |
| Audit | After implementation, before acceptance | `/gate-audit` |
| Acceptance | After audit passes, before merge | `/gate-acceptance` |

See [`CLAUDE.md`](CLAUDE.md) for the full working process, code conventions, and periodic-review
cadence.

## License

> TODO: no LICENSE file yet. TBD — to be decided before first release.
