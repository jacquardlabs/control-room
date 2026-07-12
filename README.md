# control-room

The operator seat for concurrent Claude Code work, from [Jacquard Labs](https://github.com/jacquardlabs).

Where you sit and watch the gauges and screens to see what's going on: a tabbed dashboard across every session, workflow run, and background task on your machine — churning away giving updates, and telling you when your input is needed. One fleet strip always visible (N grinding · M need you · MASTER CAUTION), one tab per work stream, the winning Flight Deck board rendering each stream's progress.

The founding opinion, and the moat: **progress and attention, not logs.** herdr, Orca, and Conductor multiplex agent terminals — panes of text streaming by, answering "what is it typing." control-room answers the operator's actual questions: *is it progressing, and which of my eight Claudes is allowed to interrupt me?* Logs live one deliberate click away, in a drawer, never ambient. This information design won a timed comprehension test against three denser alternatives before it was chosen.

## What control-room must never become

Not a log multiplexer or terminal-pane manager. Not hosted, not multi-user, not telemetered. Not a policy engine — it never answers, approves, or retries anything on its own; through T1 it is strictly read-only, and the T2 crossing into operator actions happens by written constitutional amendment, not drift. Not the per-epic board itself (that ships inside [studious](https://github.com/jacquardlabs/studious), issue #98) and not session analytics (that's [cctx](https://github.com/jacquardlabs/cctx)'s job, after the fact).

## The staged path

- **T0** — the studious andon board ships first (studious #98): hardens the schema-driven renderer and the attention-event taxonomy on real epics. control-room work before T0 is premature by construction.
- **T1 — read-only control-room:** stream discovery, generic attention detection (input-blocked · question-pending · review-ready · died · grinding), board-protocol enrichment, tabs + fleet strip, notifications with an acknowledge loop, per-stream cost vitals.
- **T2 — input-back:** resolve a parked story, answer a pending question, from the app — the human acting through a surface, with an honest action log. Read-only ends here, in writing.
- **T3 — kick-off:** launch epics, workflows, and headless sessions from the chair. The all-in-one operator platform wrapping whatever workflow — entered only after a written vendor-landscape re-check.
- **T4 — the desktop appliance:** a packaged desktop app (Tauri-class shell, winnow's Phase-4 packaging pattern) with Claude credentialing through the Agent SDK — the user's own subscription, a first-run auth doctor showing which credential is active and what it bills. Menubar caution light, login-item persistence, native notifications.

## Enabling hook-first detection

Attention detection works out of the box via poll-fallback (reading each
stream's own disk state directly — see `control_room/attention/`). To make
it hook-first instead — synchronous with Claude Code's own notification
decisions, rather than bounded by a poll interval — install the hook script
and register it:

```
uv tool install .    # from this repo root; resolves `control-room-attention-hook` on PATH
```

Then merge `control_room/attention/hooks.json`'s `"hooks"` block into your
`~/.claude/settings.json`. Poll-fallback keeps covering every stream either
way — background tasks can't fire hooks at all regardless of this step, and
this step only makes detection faster for the streams that can.

## Notifications and acknowledging

An OS notification (`osascript`, macOS only for now) fires once per needs-you
state change per stream -- never a repeat for the same unacknowledged state,
and debounced against a detector flickering near a classification boundary.
Acknowledge from the wall's MASTER CAUTION button (every need-you stream at
once) or a tab's own board button (that stream only); acknowledging stops the
blink but never touches the event log -- it's local render state, and it
survives a server restart on its own (`~/.control-room/ack-state.json`, or
`$CONTROL_ROOM_HOME/ack-state.json` if set).

## Status

T1 build underway, behind the portfolio WIP cap: stream discovery, generic attention detection, board-protocol enrichment, the fleet shell (server, wall, tabs, SSE), notifications with an acknowledge loop, and per-stream cost vitals have shipped (see `control_room/attention/`, `control_room/board/`, `control_room/shell/`, and `control_room/cost/`, above). See `docs/founding-note.md` for the full vision and its named tensions, `docs/design-history.md` for how the Flight Deck design was chosen, `PRODUCT.md` for product context, and the T1/T2/T3 milestones for the story breakdown.

## License

TBD (decided before first release).
