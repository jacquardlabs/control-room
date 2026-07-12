from __future__ import annotations

from control_room.gitmeta import resolve_worktree_info
from tests.conftest import add_linked_worktree, make_main_repo


def test_main_tree_resolves_project_root_and_branch(tmp_path):
    root = make_main_repo(tmp_path / "control-room", branch="main")

    info = resolve_worktree_info(root)

    assert info.project_root == str(root)
    assert info.project_name == "control-room"
    assert info.worktree_name is None
    assert info.git_branch == "main"


def test_linked_worktree_resolves_back_to_main_project(tmp_path):
    main_root = make_main_repo(tmp_path / "control-room", branch="main")
    worktree_root = add_linked_worktree(
        main_root,
        tmp_path / "control-room" / ".studious" / "worktrees" / "t1" / "stream-discovery",
        name="stream-discovery",
        branch="epic/t1--stream-discovery",
    )

    info = resolve_worktree_info(worktree_root)

    assert info.project_root == str(main_root)
    assert info.project_name == "control-room"
    assert info.worktree_name == "stream-discovery"
    assert info.git_branch == "epic/t1--stream-discovery"


def test_resolves_from_a_subdirectory_of_the_worktree(tmp_path):
    main_root = make_main_repo(tmp_path / "proj", branch="main")
    worktree_root = add_linked_worktree(
        main_root, tmp_path / "proj-wt", name="wt", branch="feature"
    )
    nested = worktree_root / "src" / "pkg"
    nested.mkdir(parents=True)

    info = resolve_worktree_info(nested)

    assert info.worktree_name == "wt"
    assert info.git_branch == "feature"


def test_non_git_directory_returns_none(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    assert resolve_worktree_info(scratch) is None


def test_dangling_worktree_pointer_degrades_without_raising(tmp_path):
    worktree_root = tmp_path / "orphan"
    worktree_root.mkdir()
    (worktree_root / ".git").write_text(
        "gitdir: /nonexistent/.git/worktrees/orphan\n", encoding="utf-8"
    )

    info = resolve_worktree_info(worktree_root)

    assert info.project_name == "orphan"
    assert info.worktree_name == "orphan"
    assert info.git_branch is None
