# control-room — agent instructions

The operator seat for concurrent Claude Code work: fleet strip + stream tabs +
needs-you queue, progress-and-attention information design (never logs). Currently a
**design and backlog repo — no code.** Build begins at T1's entry gate (studious #98
board shipped; attention schema hardened on a real epic), behind the portfolio WIP
cap. Do not start implementing because a session drifted here; backlog grooming, spec
work, and design-doc drafting are in scope now — code is not, until T1 opens.

## Load-bearing constraints (read before proposing anything)

- **Progress and attention, not logs.** The founding opinion. Any proposal that adds
  ambient streaming text is rejected by DESIGN.md's first anti-pattern.
- **Read-only through T1.** T2 (input-back) is entered only after a written
  PRODUCT.md amendment; the crossing is deliberate, never drift.
- **Adopt, don't fork:** the board renderer and the board/attention event schema are
  owned by studious (#98). control-room consumes them; schema changes are proposed
  upstream. The attention taxonomy stays generic — no studious-isms in shared vocabulary.
- **cctx overlap is a library question, never a merge** (settled 2026-07-07): shared
  transcript-parsing code gets extracted or vendored, but the products stay distinct
  (cctx = analyst-after; control-room = operator-during).
- **Uncertainty degrades to `grinding`, never to a false amber.** False needs-you is
  the product-killing failure mode; every detector ships with fixtures.

## Working process

Spec → plan → build. Design specs in `docs/specs/`, plans in `docs/plans/`, dated.
Founding vision and its named tensions: `docs/founding-note.md`. How the design was
chosen (concepts → riffs → timed test → Flight Deck v2): `docs/design-history.md`.
The T1/T2/T3 milestones carry the story decomposition; every story still passes the
gates when picked up — the backlog records intent, not gate exemption.

## Review workflow

### Context documents

- **PRODUCT.md** — personas, principles, NOT-building list, known problems (incl. the standing vendor-landscape re-check rule). Read before any product decision.
- **DESIGN.md** — the attention taxonomy, surface conventions, anti-patterns. Read before changing anything users see. (CLAUDE.md owns *how the code is written*; DESIGN.md owns *the user-facing surface*.)

### Code conventions (for when T1 opens)

- **Python** — 3.11+, `uv`; the server is viva-pattern stdlib-only (no web framework); type hints required; Pydantic models for the stream/attention schema — never raw dicts.
- **Frontend** — one committed self-contained page (no build step, no CDN); the renderer arrives from studious #98 as an adopted package/file, tracked upstream.
- **Linter** — Ruff with C4,SIM,PERF,B,RUF,PIE; run `ruff check` before pushing.
- **Tests** — new features require tests; bug fixes require regression tests. Attention detectors get golden transcript fixtures per taxonomy state before T1 exit; renderer changes are proposed upstream with their fixtures.

### Quality gates

| Gate | When | Command |
|------|------|---------|
| Should we build? | Before any engineering | `/gate-should-we-build [idea]` |
| Design review | After design doc, before implementation | `/gate-design-review` |
| Audit | After implementation, before acceptance | `/gate-audit` |
| Acceptance | After audit passes, before merge | `/gate-acceptance` |

### Periodic reviews

| Review | Cadence | Command |
|--------|---------|---------|
| Codebase health | Weekly or pre-milestone (once code exists) | `/deep-review codebase` |
| Interface health | Monthly or post-surface-changes | `/deep-review interface` |
| Architecture | Quarterly or pre-major-feature | `/deep-review architecture` |
| Product health | Monthly | `/deep-review product` |
| README drift | After a release or feature batch | `/deep-review readme` |
| All reviews + summary | As needed | `/deep-review` |

### After each review

1. Fix any **Critical** findings before the next feature
2. File **Important** findings as tasks to address this cycle
3. Log **Track** findings (lowest tier — revisit next cycle); they compound if ignored
4. Update context docs if the review surfaced changes:
   - `/deep-review product` updates PRODUCT.md
   - `/deep-review interface` updates DESIGN.md
   - `/deep-review architecture` updates CLAUDE.md
   - `/deep-review readme` proposes a README.md diff
