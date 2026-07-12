"""Behavioral tests for the shipped page's own inline JS.

`test_shell_static_page.py`'s own docstring names the gap directly: this
stdlib-Python-only test suite has no browser runtime, so the page's actual
*behavior* (as opposed to its markup) went untested -- keyboard
tab-switching, the liveness state machine, and the aria-live count update
all landed as structural smoke tests only. This file closes that gap for
those three, without adding a browser or a JS build step to the project:
it shells out to a system `node` (Node ships a real `document`-free JS
engine; no npm install, no jsdom, no new project dependency) and executes
source extracted *verbatim* from the real, committed `static/index.html`
-- never a hand-copied reimplementation that could silently drift from
what actually ships.

Two things are exercised:

1. `nextTabIndex` and `classifyLiveness` -- small, pure, DOM-independent
   functions this story's fix pulled out of `onTabKeydown`/`updateLiveness`
   specifically so the keyboard-nav and liveness-classification logic each
   handler defers to could be unit-tested at all, without a DOM. Both
   handlers still call these exact functions; this was a behavior-preserving
   extraction, not new logic.
2. The real `source.onmessage` handler, end to end, against a minimal
   hand-rolled DOM stub (a few fake elements, no jsdom) -- proving a
   payload's `need_you`/`master_caution` actually reaches the aria-live
   count span and the MASTER CAUTION button, through the exact code path
   the browser runs, not a reimplementation of it.

Full tab-creation/reconciliation DOM behavior (creating tab/panel elements,
click handling, focus movement) stays untested outside a real browser --
the same limitation `test_shell_static_page.py` already names, now
narrowed rather than total.

Skipped, not failed, when `node` isn't on PATH: this project ships and
runs stdlib-Python-only (`control_room/shell/server.py`'s own "viva
pattern" docstring); Node is an optional, best-effort test dependency for
this one file alone, never a hard requirement to run the suite or ship
the page.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

INDEX_HTML = Path(__file__).parent.parent / "control_room" / "shell" / "static" / "index.html"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    NODE is None, reason="node not on PATH -- optional JS behavioral pass"
)


def _html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _extract_function(html: str, name: str) -> str:
    """Pull one top-level `function <name>(...) { ... }` out of the page's
    inline script by brace-counting from its header -- robust to nested
    braces in the body, unlike a single regex match."""
    header = re.search(r"function\s+" + re.escape(name) + r"\s*\([^)]*\)\s*\{", html)
    assert header, f"{name} not found in {INDEX_HTML}"
    depth = 0
    for i in range(header.end() - 1, len(html)):
        if html[i] == "{":
            depth += 1
        elif html[i] == "}":
            depth -= 1
            if depth == 0:
                return html[header.start() : i + 1]
    raise AssertionError(f"unbalanced braces extracting {name} from {INDEX_HTML}")


def _run_node(js_source: str) -> str:
    result = subprocess.run([NODE, "-e", js_source], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_next_tab_index_wraps_arrow_keys_and_jumps_home_end() -> None:
    source = _extract_function(_html(), "nextTabIndex")
    js = (
        source
        + """
        const cases = [
          nextTabIndex("ArrowRight", 0, 3),
          nextTabIndex("ArrowRight", 2, 3),  // wraps past the last tab
          nextTabIndex("ArrowLeft", 0, 3),   // wraps past the first tab
          nextTabIndex("ArrowLeft", 1, 3),
          nextTabIndex("Home", 2, 3),
          nextTabIndex("End", 0, 3),
          nextTabIndex("Tab", 0, 3),         // an unhandled key -- no navigation
        ];
        console.log(JSON.stringify(cases));
        """
    )
    assert json.loads(_run_node(js)) == [1, 0, 2, 0, 0, 2, None]


def test_format_burn_renders_units_against_context_or_empty_when_unresolved() -> None:
    source = _extract_function(_html(), "formatBurn")
    js = (
        source
        + """
        console.log(JSON.stringify([formatBurn(4.2), formatBurn(0), formatBurn(null)]));
        """
    )
    assert json.loads(_run_node(js)) == ["$4.20 session", "$0.00 session", ""]


def test_classify_liveness_distinguishes_live_stalled_and_error() -> None:
    source = _extract_function(_html(), "classifyLiveness")
    js = (
        source
        + """
        console.log(JSON.stringify([
          classifyLiveness(2, 9, false),
          classifyLiveness(10, 9, false),
          classifyLiveness(1, 9, true),
        ]));
        """
    )
    live, stalled_by_elapsed, stalled_by_error = json.loads(_run_node(js))
    assert live["state"] == "live"
    assert "updated 2s ago" in live["text"]
    assert stalled_by_elapsed["state"] == "stalled"
    assert "server not responding" in stalled_by_elapsed["text"]
    assert stalled_by_error["state"] == "stalled"
    assert "server not responding" in stalled_by_error["text"]


_DOM_STUB = """
class FakeClassList {
  constructor() { this._set = new Set(); }
  add(c) { this._set.add(c); }
  remove(c) { this._set.delete(c); }
  toggle(c, force) {
    const has = this._set.has(c);
    const want = force === undefined ? !has : !!force;
    if (want) this._set.add(c); else this._set.delete(c);
  }
  contains(c) { return this._set.has(c); }
}

class FakeElement {
  constructor() {
    this._textContent = "";
    // Real DOM `textContent` stringifies whatever it's assigned (e.g. a
    // bare number, as `render()` assigns wall counts directly) -- matched
    // here via an accessor so this stub can't silently pass a type the
    // real DOM would have coerced.
    Object.defineProperty(this, "textContent", {
      get() { return this._textContent; },
      set(v) { this._textContent = String(v); },
    });
    this.hidden = false;
    this.dataset = {};
    this.classList = new FakeClassList();
    this._attrs = {};
    this.children = [];
  }
  setAttribute(k, v) { this._attrs[k] = String(v); }
  getAttribute(k) { return this._attrs[k]; }
  addEventListener() {}
  appendChild(child) { this.children.push(child); return child; }
  remove() {}
  querySelector() { return null; }
  focus() {}
}

const registry = {};
[
  "tabbar", "panels", "empty-state", "liveness", "liveness-text",
  "master-caution", "caution-count", "count-grinding", "count-review",
  "count-need-you", "burn-value",
].forEach((id) => { registry[id] = new FakeElement(); });

global.document = {
  getElementById(id) { return registry[id] || null; },
  createElement() { return new FakeElement(); },
};

class FakeEventSource {
  constructor(url) { this.url = url; FakeEventSource.lastInstance = this; }
}
global.EventSource = FakeEventSource;
global.window = global;
"""


def test_render_updates_the_aria_live_need_you_count_and_master_caution() -> None:
    """Drives the real `source.onmessage` handler (JSON.parse -> render,
    exactly the browser's own code path) against a payload with
    `need_you=2`/`master_caution=true`, and asserts the aria-live count
    span and the MASTER CAUTION button actually reflect it -- not a
    reimplementation of `render`, the shipped function itself."""
    script = _html().split("<script>", 1)[1].rsplit("</script>", 1)[0]
    payload = {
        "generated_at": "2026-07-12T00:00:00+00:00",
        "poll_interval_seconds": 3.0,
        "wall": {
            "grinding": 1,
            "review_ready": 0,
            "need_you": 2,
            "unacknowledged_need_you": 2,
            "master_caution": True,
            "aggregate_burn_usd": None,
        },
        "streams": [],
    }
    js = (
        _DOM_STUB
        + script
        + f"""
        FakeEventSource.lastInstance.onmessage({{ data: {json.dumps(json.dumps(payload))} }});
        console.log(JSON.stringify({{
          needYou: registry["count-need-you"].textContent,
          grinding: registry["count-grinding"].textContent,
          cautionCount: registry["caution-count"].textContent,
          blinking: registry["master-caution"].classList.contains("blink"),
        }}));
        process.exit(0);
        """
    )
    result = json.loads(_run_node(js))
    assert result["needYou"] == "2"
    assert result["grinding"] == "1"
    assert result["cautionCount"] == "2"
    assert result["blinking"] is True


def test_render_malformed_frame_is_caught_not_thrown() -> None:
    """The try/catch this fix added around `JSON.parse`/`render` in
    `source.onmessage` -- a malformed frame must not throw uncaught (which
    would otherwise silently abort the handler mid-update, potentially
    leaving `lastMessageAt` looking fresh over broken/partial content)."""
    script = _html().split("<script>", 1)[1].rsplit("</script>", 1)[0]
    js = (
        _DOM_STUB
        + script
        + """
        FakeEventSource.lastInstance.onmessage({ data: "not json" });
        console.log(JSON.stringify({
          state: registry["liveness"].dataset.state,
          text: registry["liveness-text"].textContent,
        }));
        process.exit(0);
        """
    )
    result = json.loads(_run_node(js))
    assert result["state"] == "stalled"
