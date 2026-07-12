from __future__ import annotations

import json

from control_room.discovery.interactive import discover_interactive_sessions, pid_is_alive
from control_room.models import StreamKind
from tests.conftest import add_linked_worktree, make_main_repo, write_session_file


def test_discovers_one_record_per_session_file(tmp_path):
    main_root = make_main_repo(tmp_path / "proj")
    worktree = add_linked_worktree(main_root, tmp_path / "proj-wt", name="wt", branch="feature")
    sessions_dir = tmp_path / "sessions"
    write_session_file(sessions_dir, pid=111, session_id="sid-a", cwd=str(worktree))

    records = discover_interactive_sessions(sessions_dir)

    assert len(records) == 1
    record = records[0]
    assert record.kind == StreamKind.INTERACTIVE
    assert record.id == "interactive:sid-a"
    assert record.pid == 111
    assert record.worktree_name == "wt"
    assert record.git_branch == "feature"
    assert record.project_name == "proj"


def test_missing_sessions_dir_returns_empty(tmp_path):
    assert discover_interactive_sessions(tmp_path / "nope") == []


def test_malformed_session_file_is_skipped_not_raised(tmp_path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "999.json").write_text("not json{{{", encoding="utf-8")

    assert discover_interactive_sessions(sessions_dir) == []


def test_multiple_sessions_all_appear(tmp_path):
    sessions_dir = tmp_path / "sessions"
    for i, pid in enumerate((100, 200, 300)):
        write_session_file(sessions_dir, pid=pid, session_id=f"sid-{i}", cwd=str(tmp_path))

    records = discover_interactive_sessions(sessions_dir)

    assert {r.pid for r in records} == {100, 200, 300}


def test_cwd_falls_back_to_transcript_when_session_file_lacks_it(tmp_path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    path = sessions_dir / "555.json"
    path.write_text(json.dumps({"pid": 555, "sessionId": "sid-fallback"}), encoding="utf-8")

    projects_dir = tmp_path / "projects"
    encoded = str(tmp_path / "somewhere").replace("/", "-")
    project_dir = projects_dir / encoded
    project_dir.mkdir(parents=True)
    (project_dir / "sid-fallback.jsonl").write_text(
        json.dumps(
            {
                "sessionId": "sid-fallback",
                "timestamp": "2026-07-12T00:00:00Z",
                "cwd": str(tmp_path / "somewhere"),
                "gitBranch": "from-transcript",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    records = discover_interactive_sessions(sessions_dir, projects_dir=projects_dir)

    assert len(records) == 1
    assert records[0].cwd == str(tmp_path / "somewhere")
    assert records[0].git_branch == "from-transcript"


def test_pid_is_alive_true_for_current_process():
    import os

    assert pid_is_alive(os.getpid()) is True


def test_pid_is_alive_false_for_reaped_pid():
    import subprocess

    proc = subprocess.Popen(["true"])
    proc.wait()

    assert pid_is_alive(proc.pid) is False


def test_pid_is_alive_false_for_none():
    assert pid_is_alive(None) is False
