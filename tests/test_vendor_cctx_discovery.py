"""Confirms the vendored cctx parsing copy carries an explicit version/sync marker
(the stream-discovery story's acceptance criterion, verbatim) and that the
vendored functions still work standalone against a fixture tree.
"""

from __future__ import annotations

import json
import re

from control_room.vendor import cctx_discovery


def test_vendor_marker_is_present_and_looks_like_a_commit_and_version():
    assert re.fullmatch(r"[0-9a-f]{40}", cctx_discovery.CCTX_VENDOR_SOURCE_COMMIT)
    assert re.fullmatch(r"\d+\.\d+\.\d+", cctx_discovery.CCTX_VENDOR_SOURCE_VERSION)


def test_vendor_header_documents_source_and_sync_policy():
    doc = cctx_discovery.__doc__ or ""
    assert "VENDORED COPY" in doc
    assert "github.com/jacquardlabs/cctx" in doc
    assert "Sync policy" in doc


def test_find_project_dir_round_trips_against_a_fixture(tmp_path):
    base = tmp_path / "projects"
    cwd = tmp_path / "some" / "project"
    encoded = str(cwd).replace("/", "-")
    (base / encoded).mkdir(parents=True)
    (base / encoded / "sid.jsonl").write_text(
        json.dumps({"sessionId": "sid", "cwd": str(cwd), "timestamp": "2026-07-12T00:00:00Z"})
        + "\n",
        encoding="utf-8",
    )

    found = cctx_discovery.find_project_dir(cwd, base=base)

    assert found == base / encoded


def test_list_projects_reads_sessions_from_fixture(tmp_path):
    base = tmp_path / "projects"
    cwd = tmp_path / "proj"
    encoded = str(cwd).replace("/", "-")
    project_dir = base / encoded
    project_dir.mkdir(parents=True)
    (project_dir / "sid.jsonl").write_text(
        json.dumps(
            {
                "sessionId": "sid",
                "cwd": str(cwd),
                "gitBranch": "main",
                "timestamp": "2026-07-12T00:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    (project,) = cctx_discovery.list_projects(base=base)

    assert project.session_count == 1
    assert project.sessions[0].session_id == "sid"
    assert project.sessions[0].git_branch == "main"
