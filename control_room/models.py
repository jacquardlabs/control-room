"""Pydantic models for the stream-discovery schema.

Discovery's job is existence + liveness bookkeeping only -- the richer
attention taxonomy (grinding / input-blocked / question-pending / parked /
review-ready / died / done, DESIGN.md's "Semantic palette") belongs to the
attention-detection story. Discovery never assigns an attention state; it
only ever answers "does this stream currently exist, and have we lost
contact with it."
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class StreamKind(StrEnum):
    """What kind of Claude Code stream this is -- generic, not studious-specific.

    PRODUCT.md principle 7 ("wraps whatever workflow"): this vocabulary
    names *how a stream was launched*, never a downstream product's own
    concepts.
    """

    INTERACTIVE = "interactive"
    WORKFLOW_RUN = "workflow_run"
    BACKGROUND_TASK = "background_task"


class LiveState(StrEnum):
    """Discovery's own liveness bookkeeping -- distinct from the attention taxonomy.

    A stream transitions live -> grace -> gone as consecutive polls fail to
    find evidence of life, and resets to `live` the instant evidence
    reappears (self-healing against one flaky read). `gone` is never
    actually returned by `StreamRegistry.poll()` -- reaching it means the
    record is dropped from the result set (aged out) instead.
    """

    LIVE = "live"
    GRACE = "grace"
    GONE = "gone"


class StreamRecord(BaseModel):
    """One discovered Claude Code stream, at the granularity discovery owns.

    Field groups:
      - identity: `id`, `kind`, `label`
      - location: `cwd`, `project_root`, `project_name`, `worktree_name`, `git_branch`
      - lineage: `parent_stream_id` -- the id of the stream that dispatched
        this one, when known
      - liveness bookkeeping: `live_state`, `consecutive_misses`, `first_seen`, `last_seen`
      - provenance: `source_path`, the on-disk artifact this record was read from
    """

    id: str
    kind: StreamKind
    label: str
    cwd: str
    project_root: str | None = None
    project_name: str | None = None
    worktree_name: str | None = None
    git_branch: str | None = None
    parent_stream_id: str | None = None
    """The id of the stream that dispatched this one -- e.g. a Workflow-tool
    run's dispatching interactive session (`interactive:<session-id>`).
    `None` for a stream nothing else dispatched (an interactive session, a
    daemon-launched job). Reported live (2026-07): two Workflow runs from one
    session rendered as flat, unrelated tabs with no way to tell they shared
    a dispatcher -- this is discovery's own fact about provenance, the same
    category as `project_root`/`worktree_name` above, not a derived opinion
    about grouping (that stays downstream, in sort order and rendering)."""
    pid: int | None = None
    raw_status: str | None = None
    live_state: LiveState = LiveState.LIVE
    consecutive_misses: int = 0
    first_seen: datetime
    last_seen: datetime
    source_path: str
