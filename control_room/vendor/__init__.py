"""Vendored copies of code shared with cctx (github.com/jacquardlabs/cctx).

Vendored, not extracted into a shared library -- settled 2026-07-07 (see
docs/founding-note.md, "cctx overlap is a library question, never a merge"):
a real shared library adds a cross-repo release/versioning step in tension
with the stdlib-only, no-build-step convention both viva-pattern tools
follow. Upstream fixes flow in by manual re-sync, not by fork -- each
vendored module carries its own source-commit marker (see
`cctx_discovery.py`).
"""
