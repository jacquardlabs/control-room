"""The viva-pattern local server: stdlib only, no web framework, no CDN.

Two routes:

- `GET /` (or `/index.html`) -- the committed self-contained page
  (`static/index.html`), read from disk and served as-is. Reading it fresh
  per request (rather than embedding it in the process) means the running
  server always serves exactly the checked-in file -- nothing baked in at
  import time to go stale.
- `GET /events` -- Server-Sent Events. Each connection gets its own
  `control_room.shell.state.FleetState` and polls it in a loop for the
  lifetime of the connection, writing one `data: <json>\\n\\n` frame per
  tick. One `FleetState` per connection (not one shared instance) means two
  browser tabs never corrupt each other's liveness bookkeeping -- the
  documented, deliberately-unaddressed multi-instance question in the
  design doc's open questions, resolved here the simple way: isolate,
  don't share.

`ThreadingHTTPServer` gives every request (including a long-lived SSE
stream) its own thread, so one slow/open connection never blocks another
request -- and `daemon_threads = True` (its own default) means those
threads never block process shutdown.
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from control_room import paths
from control_room.shell.payload import build_fleet_payload
from control_room.shell.state import FleetState

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4173
DEFAULT_POLL_INTERVAL = 3.0
"""Seconds between SSE ticks. Generous relative to stream-discovery's own
<=5s poll-interval bar so a slow client/network never falls behind, tight
enough that the wall's liveness indicator (design doc) reads as "quiet, but
alive" rather than stale."""

STATIC_DIR = Path(__file__).parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"


class FleetHTTPServer(ThreadingHTTPServer):
    """Carries the disk locations and poll cadence every request needs --
    injected here (not read from `control_room.paths` inside the handler)
    so tests can point a server at a `tmp_path` fixture instead of the real
    `~/.claude` tree."""

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_cls: type[BaseHTTPRequestHandler],
        *,
        sessions_dir: Path,
        jobs_dir: Path,
        events_dir: Path,
        index_html: Path = INDEX_HTML,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ) -> None:
        super().__init__(server_address, handler_cls)
        self.sessions_dir = sessions_dir
        self.jobs_dir = jobs_dir
        self.events_dir = events_dir
        self.index_html = index_html
        self.poll_interval = poll_interval


class FleetRequestHandler(BaseHTTPRequestHandler):
    server: FleetHTTPServer  # narrows the inherited `Any`-typed attribute

    def log_message(self, format: str, *args: object) -> None:
        logger.info("%s - %s", self.address_string(), format % args)

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._serve_static_page()
        elif self.path == "/events":
            self._serve_events()
        else:
            self.send_error(404, "not found")

    def _serve_static_page(self) -> None:
        try:
            body = self.server.index_html.read_bytes()
        except OSError:
            self.send_error(500, "static page unavailable")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_events(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        state = FleetState(self.server.sessions_dir, self.server.jobs_dir, self.server.events_dir)
        try:
            while True:
                self._write_event(state)
                time.sleep(self.server.poll_interval)
        except (BrokenPipeError, ConnectionResetError):
            return  # client navigated away/closed the tab -- not a server error

    def _write_event(self, state: FleetState) -> None:
        snapshot = state.poll(now=datetime.now(UTC))
        payload = build_fleet_payload(snapshot, poll_interval_seconds=self.server.poll_interval)
        frame = f"data: {payload.model_dump_json()}\n\n".encode()
        self.wfile.write(frame)
        self.wfile.flush()


def build_server(
    server_address: tuple[str, int] = (DEFAULT_HOST, DEFAULT_PORT),
    *,
    sessions_dir: Path | None = None,
    jobs_dir: Path | None = None,
    events_dir: Path | None = None,
    index_html: Path = INDEX_HTML,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
) -> FleetHTTPServer:
    return FleetHTTPServer(
        server_address,
        FleetRequestHandler,
        sessions_dir=sessions_dir or paths.sessions_dir(),
        jobs_dir=jobs_dir or paths.jobs_dir(),
        events_dir=events_dir or paths.attention_events_dir(),
        index_html=index_html,
        poll_interval=poll_interval,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="control-room", description="The fleet shell server.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL)
    args = parser.parse_args(argv)

    server = build_server((args.host, args.port), poll_interval=args.poll_interval)
    print(f"control-room listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
