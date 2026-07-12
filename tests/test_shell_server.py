"""End-to-end over a real socket: `GET /` serves the static page, `GET
/events` streams SSE frames the payload schema promises, unknown paths 404.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from control_room.registry import GRACE_AFTER_MISSES
from control_room.shell.server import FleetHTTPServer, FleetRequestHandler, build_server
from tests.conftest import write_session_file


def _spawn_sleeper() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])


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


def test_reconnect_after_a_dropped_connection_never_un_dies_a_died_stream(
    tmp_path: Path,
) -> None:
    """The audit-critical regression: a native `EventSource` reconnect (a
    brand-new HTTP connection to an *already-running* server -- exactly
    what the browser's own auto-reconnect does after any transient drop,
    since `static/index.html`'s `onerror` deliberately never calls
    `.close()`) must not revert an already-resolved `died` stream back to
    `grinding`.

    Before this fix, `_serve_events` handed every new connection its own
    fresh `FleetState`, so a reconnect was indistinguishable from a
    brand-new tab: `_previous_event` and the registry's own liveness
    bookkeeping both started over from nothing, silently un-dying the
    stream for the several poll intervals it took to re-earn
    `GRACE_AFTER_MISSES` misses from scratch -- MASTER CAUTION going dark
    and the needs-you count dropping for a stream that had, in fact, died.
    """
    sessions_dir = tmp_path / "sessions"
    proc = _spawn_sleeper()
    try:
        write_session_file(sessions_dir, pid=proc.pid, session_id="s-reconnect", cwd=str(tmp_path))

        with _running_server(tmp_path, poll_interval=0.03) as base_url:
            with urllib.request.urlopen(f"{base_url}/events", timeout=5) as first:
                first_state = json.loads(_read_one_frame(first))["streams"][0]["attention_state"]
                assert first_state == "grinding"

                proc.kill()
                proc.wait()

                died_state = None
                for _ in range(GRACE_AFTER_MISSES + 5):
                    died_state = json.loads(_read_one_frame(first))["streams"][0]["attention_state"]
                    if died_state == "died":
                        break
                assert died_state == "died"
            # `first`'s `with` block just closed the connection -- a real
            # drop, not a clean client shutdown the server can tell apart
            # from a browser's silent reconnect.

            with urllib.request.urlopen(f"{base_url}/events", timeout=5) as second:
                reconnected = json.loads(_read_one_frame(second))
    finally:
        proc.kill()
        proc.wait()

    assert reconnected["streams"][0]["attention_state"] == "died"
    assert reconnected["wall"]["need_you"] == 1
    assert reconnected["wall"]["master_caution"] is True


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
