"""Pure-filesystem worktree/project resolution -- no `git` subprocess calls.

Reads git's own on-disk worktree pointer files directly:

- a linked worktree's `.git` is a *file* containing `gitdir: <main>/.git/worktrees/<name>`
- that `<name>` dir holds `commondir` (relative path back to the main `.git`),
  and `HEAD` (the worktree's current ref)
- the main tree's `.git` is a directory; its own `HEAD` is the current ref

Reading these directly (rather than shelling out to `git`) keeps stream
discovery read-only by construction with no subprocess dependency, and
makes it trivially fixturable with plain directories in tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_HEAD_BRANCH_PREFIX = "ref: refs/heads/"
_GITDIR_PREFIX = "gitdir:"


@dataclass(frozen=True)
class WorktreeInfo:
    project_root: str
    """The main repository's working-tree root (never a linked worktree's own root)."""
    project_name: str
    """`project_root`'s directory name -- the display label for the project."""
    worktree_name: str | None
    """The linked worktree's name, or None when `cwd` is the main tree itself."""
    git_branch: str | None
    """Best-effort current branch; None on a detached HEAD or unreadable ref."""


def resolve_worktree_info(cwd: str | Path) -> WorktreeInfo | None:
    """Walk up from `cwd` to the nearest `.git` and classify it.

    Returns None if no `.git` is found above `cwd` at all (not a git
    checkout -- e.g. a scratch directory). Never raises: a malformed or
    unreadable git-internal file degrades to a best-effort partial result
    rather than failing the whole poll over one stream.
    """
    start = Path(cwd)
    for candidate in (start, *start.parents):
        git_path = candidate / ".git"
        if git_path.is_dir():
            return _from_main_tree(candidate, git_path)
        if git_path.is_file():
            return _from_linked_worktree(candidate, git_path)
    return None


def _from_main_tree(root: Path, git_dir: Path) -> WorktreeInfo:
    return WorktreeInfo(
        project_root=str(root),
        project_name=root.name,
        worktree_name=None,
        git_branch=_read_branch(git_dir),
    )


def _from_linked_worktree(worktree_root: Path, git_file: Path) -> WorktreeInfo:
    pointer = _read_gitdir_pointer(git_file)
    if pointer is None or not pointer.is_dir():
        # Malformed or dangling pointer -- still name the worktree itself,
        # just without a resolved main-project root.
        return WorktreeInfo(
            project_root=str(worktree_root),
            project_name=worktree_root.name,
            worktree_name=worktree_root.name,
            git_branch=None,
        )

    worktree_name = pointer.name
    main_git_dir = _read_commondir(pointer) or pointer
    project_root = main_git_dir.parent

    return WorktreeInfo(
        project_root=str(project_root),
        project_name=project_root.name,
        worktree_name=worktree_name,
        git_branch=_read_branch(pointer),
    )


def _read_gitdir_pointer(git_file: Path) -> Path | None:
    try:
        text = git_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text.startswith(_GITDIR_PREFIX):
        return None
    return Path(text[len(_GITDIR_PREFIX) :].strip())


def _read_commondir(worktree_git_dir: Path) -> Path | None:
    commondir_file = worktree_git_dir / "commondir"
    try:
        relative = commondir_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        return (worktree_git_dir / relative).resolve()
    except OSError:
        return None


def _read_branch(git_dir: Path) -> str | None:
    try:
        text = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if text.startswith(_HEAD_BRANCH_PREFIX):
        return text[len(_HEAD_BRANCH_PREFIX) :]
    return None  # detached HEAD -- best-effort only
