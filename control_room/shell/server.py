"""The viva-pattern local server: stdlib only, no web framework, no CDN.

Two routes:

- `GET /` (or `/index.html`) -- the committed self-contained page
  (`static/index.html`), read from disk and served as-is. Reading it fresh
  per request (rather than embedding it in the process) means the running
  server always serves exactly the checked-in file -- nothing baked in at
  import time to go stale.
- `GET /events` -- Server-Sent Events. Every connection reads from the
  *same* `FleetState`, owned by `FleetHTTPServer` itself and advanced by
  one dedicated background thread (`_poll_loop`) that calls `state.poll()`
  once per `poll_interval`, caches the result, and wakes every waiting
  connection.

  This is not the first design tried here -- the first cut gave each
  `/events` connection its own `FleetState`, reasoning that isolating
  per-connection bookkeeping was the simplest way to stop two browser tabs
  from corrupting each other's liveness state. That reasoning missed a
  case: the page's `EventSource` auto-reconnects on any transient drop
  (`static/index.html`'s `onerror` never calls `.close()`, by design, so
  the browser's native retry keeps the stream alive across a blip) --
  and a reconnect looks identical to a brand-new tab opening. Every silent
  reconnect was quietly handing the resumed connection a *fresh*
  `FleetState`: `_previous_event` empty, `StreamRegistry._known` empty, so
  a stream already resolved `died` (a sticky, once-observed terminal state
  -- see `control_room.shell.state`'s module docstring) would revert to
  `grinding` for the several seconds it took the registry to re-earn
  `GRACE_AFTER_MISSES` misses from scratch -- MASTER CAUTION going dark and
  the needs-you count dropping for a stream that had, in fact, died. That
  is the one failure mode this whole product exists to prevent.

  The fix is to decouple "how often the fleet's state actually advances"
  from "how many HTTP connections currently exist": exactly one poll
  loop, owned by the server (not any connection), ticks the shared
  `FleetState` every `poll_interval`; connections (however many, however
  they came to be open -- first load, a second tab, or a native
  reconnect after a drop) only ever *read* the latest cached snapshot and
  block for the next one. A stream's terminal-state/liveness bookkeeping
  is now keyed to the server process, never to any one HTTP connection --
  so it survives reconnects and isn't skewed by how many tabs are
  watching. A real "kill and restart the server" still resets everything,
  because that's a new process launching a new `FleetHTTPServer`, hence a
  new `FleetState` and a new poll thread from scratch -- the acceptance
  criterion this story actually asks for.

`ThreadingHTTPServer` gives every request (including a long-lived SSE
stream) its own thread, so one slow/open connection never blocks another
request -- and `daemon_threads = True` (its own default) means those
threads never block process shutdown.
"""

from __future__ import annotations

import argparse
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from control_room import paths
from control_room.board.bucket import WallBucket
from control_room.notifier import send_desktop_notification
from control_room.shell.payload import FleetPayload, StreamPayload, build_fleet_payload
from control_room.shell.state import FleetState, NotifyCallable

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4173
DEFAULT_POLL_INTERVAL = 3.0
"""Seconds between poll-loop ticks. Generous relative to stream-discovery's own
<=5s poll-interval bar so a slow client/network never falls behind, tight
enough that the wall's liveness indicator (design doc) reads as "quiet, but
alive" rather than stale."""

STATIC_DIR = Path(__file__).parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"


class FleetHTTPServer(ThreadingHTTPServer):
    """Carries the one shared `FleetState` and the background thread that
    advances it, plus the disk locations and poll cadence every request
    needs -- injected here (not read from `control_room.paths` inside the
    handler) so tests can point a server at a `tmp_path` fixture instead of
    the real `~/.claude` tree.

    `FleetState` is not thread-safe by its own contract ("call from one
    loop") -- that one loop is `_poll_loop`, started here and never called
    from anywhere else. Every `/events` connection only ever reads the
    latest cached payload through `_await_next_frame`, guarded by
    `_snapshot_cv`; no connection thread ever calls `fleet_state.poll()`
    directly. `POST /ack` is the one exception, calling `fleet_state.
    acknowledge()` directly from its own request thread -- safe per that
    method's own contract (delegates only to the lock-guarded `AckStore`).

    Defaults `notify` to the real `control_room.notifier.
    send_desktop_notification` -- this class represents the actual running
    server, where firing a real OS notification is the point. Tests that
    construct a `FleetHTTPServer` directly and might drive a stream into the
    M bucket must override this explicitly (see `tests/test_shell_server.py`)
    so a test run never shells out to `osascript`.
    """

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_cls: type[BaseHTTPRequestHandler],
        *,
        sessions_dir: Path,
        jobs_dir: Path,
        events_dir: Path,
        projects_dir: Path | None = None,
        index_html: Path = INDEX_HTML,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        ack_path: Path | None = None,
        notify: NotifyCallable | None = None,
    ) -> None:
        super().__init__(server_address, handler_cls)
        self.sessions_dir = sessions_dir
        self.jobs_dir = jobs_dir
        self.events_dir = events_dir
        self.index_html = index_html
        self.poll_interval = poll_interval

        self.fleet_state = FleetState(
            sessions_dir,
            jobs_dir,
            events_dir,
            projects_dir=projects_dir,
            ack_path=ack_path,
            notify=notify or send_desktop_notification,
        )
        self._snapshot_cv = threading.Condition()
        self._latest_payload: FleetPayload | None = None
        # Must start below _serve_events' own initial `after_seq = -1`, not
        # at 0: `await_next_frame`'s wait_for condition is `_latest_seq >
        # after_seq`, and starting this at 0 makes that condition already
        # true the instant the server object exists -- before _poll_loop's
        # first tick has necessarily run. A connection that calls
        # await_next_frame in that window gets back `_latest_payload` at
        # its still-None initial value, and `_serve_events` crashes on
        # `None.model_dump_json()`. Starting at -1 forces the condition to
        # wait for the poll loop's first real `_latest_seq += 1`, so a
        # connection can never observe a None payload.
        self._latest_seq = -1
        self._stop_polling = threading.Event()
        self._poll_thread = threading.Thread(
            target=self._poll_loop, name="fleet-state-poller", daemon=True
        )
        self._poll_thread.start()

    def _poll_loop(self) -> None:
        """The one and only caller of `FleetState.poll()` for this process's
        lifetime. Runs immediately on startup (so the first connection
        never waits a full `poll_interval` for its first frame), then once
        per `poll_interval` until `server_close()` signals stop."""
        while not self._stop_polling.is_set():
            snapshot = self.fleet_state.poll()
            payload = build_fleet_payload(snapshot, poll_interval_seconds=self.poll_interval)
            with self._snapshot_cv:
                self._latest_payload = payload
                self._latest_seq += 1
                self._snapshot_cv.notify_all()
            if self._stop_polling.wait(self.poll_interval):
                break

    def latest_payload(self) -> FleetPayload | None:
        """The most recently built payload, or `None` before the poll loop's
        first tick -- read under the same lock `_poll_loop` writes under, so
        the `/ack` handler (a different thread) never sees a torn read."""
        with self._snapshot_cv:
            return self._latest_payload

    def await_next_frame(self, after_seq: int) -> tuple[FleetPayload, int] | None:
        """Block until a snapshot newer than `after_seq` is available and
        return it, or `None` if the server is shutting down. Any number of
        connections (including several concurrent tabs, or a browser's own
        reconnect after a transient drop) can call this concurrently --
        none of them ever re-derive fleet state themselves."""
        with self._snapshot_cv:
            self._snapshot_cv.wait_for(
                lambda: self._stop_polling.is_set() or self._latest_seq > after_seq
            )
            if self._stop_polling.is_set():
                return None
            return self._latest_payload, self._latest_seq

    def server_close(self) -> None:
        self._stop_polling.set()
        with self._snapshot_cv:
            self._snapshot_cv.notify_all()
        self._poll_thread.join(timeout=5)
        super().server_close()


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

    def do_POST(self) -> None:
        if self.path == "/ack":
            self._handle_ack()
        else:
            self.send_error(404, "not found")

    def _handle_ack(self) -> None:
        """Acknowledge one stream (`{"stream_id": "..."}`) or, with no
        `stream_id` (an empty body, or none at all -- the wall's own MASTER
        CAUTION button POSTs this way), every currently-M-bucket stream at
        once. The identity acknowledged is always read from the server's own
        latest served payload, never from the request body -- an owner
        acking a stream can't accidentally acknowledge an identity that was
        never actually observed (see `FleetState.acknowledge`'s own note)."""
        try:
            stream_id = self._read_ack_stream_id()
        except ValueError as exc:
            self.send_error(400, str(exc))
            return

        latest = self.server.latest_payload()
        if latest is None:
            self._no_content()
            return

        if stream_id is not None:
            item = next((s for s in latest.streams if s.id == stream_id), None)
            if item is None:
                self.send_error(404, "unknown stream")
                return
            self._acknowledge(item)
        else:
            for item in latest.streams:
                if item.bucket is WallBucket.M:
                    self._acknowledge(item)

        self._no_content()

    def _acknowledge(self, item: StreamPayload) -> None:
        self.server.fleet_state.acknowledge(item.id, state=item.attention_state, reason=item.reason)

    def _read_ack_stream_id(self) -> str | None:
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return None
        raw = self.rfile.read(length)
        if not raw.strip():
            return None
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("malformed JSON body") from exc
        if not isinstance(body, dict):
            raise ValueError("body must be a JSON object")
        stream_id = body.get("stream_id")
        if stream_id is not None and not isinstance(stream_id, str):
            raise ValueError("stream_id must be a string")
        return stream_id

    def _no_content(self) -> None:
        self.send_response(204)
        self.end_headers()

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

        seq = -1
        try:
            while True:
                result = self.server.await_next_frame(seq)
                if result is None:
                    return  # server is shutting down
                payload, seq = result
                frame = f"data: {payload.model_dump_json()}\n\n".encode()
                self.wfile.write(frame)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return  # client navigated away/closed the tab -- not a server error


def build_server(
    server_address: tuple[str, int] = (DEFAULT_HOST, DEFAULT_PORT),
    *,
    sessions_dir: Path | None = None,
    jobs_dir: Path | None = None,
    events_dir: Path | None = None,
    projects_dir: Path | None = None,
    ack_path: Path | None = None,
    index_html: Path = INDEX_HTML,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
) -> FleetHTTPServer:
    return FleetHTTPServer(
        server_address,
        FleetRequestHandler,
        sessions_dir=sessions_dir or paths.sessions_dir(),
        jobs_dir=jobs_dir or paths.jobs_dir(),
        events_dir=events_dir or paths.attention_events_dir(),
        projects_dir=projects_dir or paths.projects_dir(),
        ack_path=ack_path or paths.ack_state_path(),
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
