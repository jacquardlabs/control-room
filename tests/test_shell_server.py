"""End-to-end over a real socket: `GET /` serves the static page, `GET
/events` streams SSE frames the payload schema promises, unknown paths 404.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from control_room.shell.server import FleetHTTPServer, FleetRequestHandler, build_server
from tests.conftest import write_session_file


@contextmanager
def _running_server(
    tmp_path: Path, *, poll_interval: float = 0.05, index_html: Path | None = None
) -> Iterator[str]:
    page = index_html or (tmp_path / "index.html")
    if index_html is None:
        page.write_text("<!doctype html><title>control-room</title>", encoding="utf-8")

    server = FleetHTTPServer(
        ("127.0.0.1", 0),
        FleetRequestHandler,
        sessions_dir=tmp_path / "sessions",
        jobs_dir=tmp_path / "jobs",
        events_dir=tmp_path / "events",
        index_html=page,
        poll_interval=poll_interval,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_root_serves_the_static_page(tmp_path: Path) -> None:
    with (
        _running_server(tmp_path) as base_url,
        urllib.request.urlopen(f"{base_url}/", timeout=5) as response,
    ):
        assert response.status == 200
        assert "text/html" in response.headers["Content-Type"]
        body = response.read().decode("utf-8")
    assert "control-room" in body


def test_build_server_serves_the_real_committed_page(tmp_path: Path) -> None:
    """`build_server`'s default `index_html` is the real, committed
    `static/index.html` -- not a test stub -- exercised end to end here so
    a path typo in `build_server` can't hide behind every other test's
    synthetic page fixture."""
    server = build_server(
        ("127.0.0.1", 0),
        sessions_dir=tmp_path / "sessions",
        jobs_dir=tmp_path / "jobs",
        events_dir=tmp_path / "events",
        poll_interval=0.05,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        with urllib.request.urlopen(f"http://{host}:{port}/", timeout=5) as response:
            body = response.read().decode("utf-8")
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert "MASTER CAUTION" in body
    assert 'role="tablist"' in body


def test_unknown_path_is_404(tmp_path: Path) -> None:
    with _running_server(tmp_path) as base_url, pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"{base_url}/nope", timeout=5)
    assert exc_info.value.code == 404


def test_events_stream_is_sse_and_matches_the_payload_schema(tmp_path: Path) -> None:
    write_session_file(tmp_path / "sessions", pid=1, session_id="s1", cwd=str(tmp_path))
    with (
        _running_server(tmp_path) as base_url,
        urllib.request.urlopen(f"{base_url}/events", timeout=5) as response,
    ):
        assert response.status == 200
        assert response.headers["Content-Type"] == "text/event-stream"
        frame = _read_one_frame(response)

    payload = json.loads(frame)
    assert "generated_at" in payload
    assert payload["poll_interval_seconds"] == pytest.approx(0.05)
    assert set(payload["wall"]) == {
        "grinding",
        "review_ready",
        "need_you",
        "unacknowledged_need_you",
        "master_caution",
        "aggregate_burn_usd",
    }
    assert len(payload["streams"]) == 1
    assert payload["streams"][0]["id"] == "interactive:s1"


def test_empty_fleet_still_streams_a_heartbeat_frame(tmp_path: Path) -> None:
    """No streams on disk at all -- the SSE connection still ticks (the
    "quiet, not stalled" liveness signal), it doesn't just go silent."""
    with (
        _running_server(tmp_path) as base_url,
        urllib.request.urlopen(f"{base_url}/events", timeout=5) as response,
    ):
        frame = _read_one_frame(response)

    payload = json.loads(frame)
    assert payload["streams"] == []
    assert payload["wall"]["grinding"] == 0


def _read_one_frame(response) -> str:
    lines = []
    while True:
        line = response.readline().decode("utf-8")
        if not line.strip():
            if lines:
                break
            continue
        lines.append(line)
    (data_line,) = lines
    assert data_line.startswith("data: ")
    return data_line[len("data: ") :]
