# Design history — how the Flight Deck was chosen (2026-07-07)

The visual and information design arrived through a same-day sequence worth recording,
because its artifacts are the evidence base for the product's founding opinion.

1. **Three concepts, one simulated epic.** Control Room (dense operator console:
   needs-you strip, DAG map, swimlanes with kickback arcs), Flow Board (kanban physics,
   rubber-stamp verdicts), and Transit Map (stories as metro lines, failed audits as a
   siding to the "fix depot") — all animated from a single simulated `/work-through`
   run: five stories, a two-cycle kickback loop, one park, one dependency unblock.

2. **Three riffs on Control Room**, varying one axis each: Amber Phosphor (palette —
   state as brightness, blink reserved for "needs a human"), Ops Map (layout —
   structure-first, agent satellites making fan-out cost visible), Flight Deck
   (metaphor — EICAS engine gauges + annunciator lamps + CAS messages; latched FIX
   lamps carrying history without a timeline).

3. **The timed comprehension test.** Four boards × four *different* randomized failure
   scenarios (so memory couldn't answer), three fixed questions per round — who
   parked, why it parked, what's blocked on it — time-to-last-correct scored, wrong
   clicks counted as the confident-misread signal, session means accumulated across
   runs. **Flight Deck won.**

4. **The UI/UX deep review** (Web Interface Guidelines pass + information-design
   critique) produced **Flight Deck v2**: acknowledgeable MASTER CAUTION button
   (aviation's actual loop — legal because ack is local render state), fix-budget
   wedges on the dial itself, blocked instruments naming their blocker, severity-major
   CAS ordering, lamps abbreviating while the drawer speaks the ledger verbatim with
   copyable resolution commands, full a11y (aria-live CAS, ●/○ lamp form, contrast,
   reduced-motion preserving meaning), and the instruments-never-move rule.

**Properties that carry into control-room:**

- **Progress-and-attention beat logs empirically** — the comprehension test is the
  receipt for the founding opinion, not a taste claim.
- **One schema, N renderers, by construction** — all four test boards consumed an
  identical state shape; the schema-driven renderer is what makes the fleet product a
  consumer of the studious board rather than a fork of it.
- **The validated palettes** (categorical five + status set, six-checks validator,
  CVD-safe on dark) and the state vocabulary transfer as-is.

The interactive artifacts (concepts, riffs, the test, v2) live in the owner's
2026-07-07 session artifact gallery; the settled direction and scope decision are
recorded on studious #98.
