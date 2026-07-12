# Epic pre-mortem — t1

Recorded at plan approval (2026-07-12). Cross-story failure modes only — each story's
own pre-mortem (if any) covers its local risks. This register is distinct from the
design doc's own pre-mortem (`docs/studious/premortems/2026-07-11-t1-design.md`),
which covers product-level failure modes for T1 as a whole; this one covers risks that
arise specifically from splitting T1 into seven separately-built, separately-gated
stories. Verified per item at the epic finale by `@agent-premortem-auditor`:
REALIZED / NOT REALIZED / CAN'T VERIFY.

## 1. Renderer/detector interface drift

`board-protocol-render` re-invents `attention-detection`'s output shape instead of
consuming it, since the two stories are built separately (possibly by different
workers with no shared context beyond the recorded interface).

**Signal it's realized:** `board-protocol-render`'s build doesn't type/test against
`attention-detection`'s actual output schema, or defines its own parallel shape for
generic-vitals data instead.

## 2. Stream-registry shape drift across four consumers

`stream-discovery`'s registry feeds `attention-detection`, `board-protocol-render`,
`fleet-shell`, and `cost-vitals`. A late field rename (to satisfy a downstream
story's need) silently breaks an earlier-landed consumer that assumed the old shape.

**Signal it's realized:** the registry schema isn't pinned explicitly enough
(documented types/fields) that later stories can check against it rather than each
inferring their own assumptions; or a downstream story's build required an
unplanned fix to a landed upstream story's registry contract.

## 3. Duplicated wall-bucket mapping

The seven-state-to-three-count (N grinding / R review-ready / M need-you) mapping is
a single, specific piece of logic the design doc defines once, but `fleet-shell` and
`board-protocol-render` are separate stories that both touch wall/tab rendering.

**Signal it's realized:** the mapping exists in more than one function/module, or
the two stories' diffs disagree on which states count toward which bucket.

## 4. Parallel-story merge collision on shared rendering surface

`notifications-ack` and `cost-vitals` are scheduled in parallel (both depend only on
`fleet-shell`), and both plausibly touch wall-rendering code (the ack/blink state and
the burn display sit close together on the same surface).

**Signal it's realized:** the second story's merge into the epic branch required
manual conflict resolution touching wall-rendering lines the first story added, or
one story's change silently regressed the other's (e.g. burn display disappearing
after the ack-loop change lands).

## 5. Foundational detection-architecture gap surfaces only at dogfood-week

The design doc's own pre-mortem (item 1) already names the risk that hook-based
detection may not fire inside Task-dispatched subagents. Because `dogfood-week` is
scheduled last and depends on all six other stories, if this gap isn't caught during
`attention-detection`'s own acceptance, it's discovered only after five more stories'
worth of work sits on top of it.

**Signal it's realized:** `attention-detection`'s story lands without an explicit
test exercising the hook path against a dispatched-agent tool call (not just the
interactive session), deferring that risk to the dogfood week instead of closing it
at the source.

## 6. Unpinned vendored parsing copy

`stream-discovery` vendors a tracked copy of cctx's transcript-parsing code (per the
design doc's schema-only-adoption decision, applied here to cctx rather than
studious). Without a version/sync marker, a later story's worker could assume fields
or behavior from a stale or drifted copy without knowing it's stale.

**Signal it's realized:** the vendored file carries no version, date, or source-commit
marker at all, or a downstream story's build silently worked around a parsing
behavior that doesn't match cctx's current actual format.
