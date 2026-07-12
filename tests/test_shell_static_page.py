"""The committed static page: self-contained/offline check, plus a
structural smoke test for the accessibility/ARIA surface the acceptance
criteria name directly (keyboard tab-switching, focus rings, aria-live on
the wall's needs-you count, an explicit liveness indicator).

This can't exercise the page's JS in a real browser (no browser runtime in
this stdlib-only test suite) -- see `control_room/shell/server.py`'s own
docstring and this story's summary for that limitation, flagged for the
accessibility pass at `/gate-audit` rather than silently assumed covered.
"""

from __future__ import annotations

import re
from pathlib import Path

INDEX_HTML = Path(__file__).parent.parent / "control_room" / "shell" / "static" / "index.html"


def _read() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def test_page_exists_and_is_utf8_text() -> None:
    assert INDEX_HTML.is_file()
    assert len(_read()) > 0


def test_no_external_network_reference_anywhere() -> None:
    """The offline/self-contained check: no CDN script, no external
    stylesheet, no web font, no ajax call -- literally no URL scheme
    substring anywhere in the file."""
    html = _read()
    assert "://" not in html


def test_no_external_script_or_link_tags() -> None:
    html = _read()
    assert not re.search(r"<script[^>]+\bsrc=", html, re.IGNORECASE)
    assert not re.search(r"<link[^>]+\brel=[\"']stylesheet[\"']", html, re.IGNORECASE)


def test_has_exactly_one_inline_style_and_one_inline_script() -> None:
    html = _read()
    assert html.count("<style>") == 1
    assert html.count("<script>") == 1


def test_declares_light_and_dark_chrome() -> None:
    html = _read()
    assert "prefers-color-scheme: dark" in html


def test_reduced_motion_keeps_caution_meaning() -> None:
    html = _read()
    assert "prefers-reduced-motion: reduce" in html


def test_wall_needs_you_count_is_aria_live() -> None:
    html = _read()
    assert re.search(r'class="count count-m"[^>]*aria-live="polite"', html)


def test_tabbar_is_an_accessible_tablist() -> None:
    html = _read()
    assert 'role="tablist"' in html


def test_master_caution_is_a_real_button() -> None:
    html = _read()
    assert re.search(r'<button[^>]+id="master-caution"[^>]*aria-pressed="false"', html)


def test_liveness_indicator_present_with_distinct_states() -> None:
    html = _read()
    assert 'id="liveness"' in html
    assert 'data-state="connecting"' in html
    assert 'data-state="stalled"' in html or '"stalled"' in html
    assert 'data-state="live"' in html or '"live"' in html


def test_keyboard_tab_switching_handler_present() -> None:
    html = _read()
    assert "onTabKeydown" in html
    assert "ArrowRight" in html and "ArrowLeft" in html


def test_no_ambient_log_or_transcript_surface() -> None:
    """No surface renders streaming/raw transcript text -- the board
    fragment renders instrument state/reason/CAS lines only, and nothing
    in the shell page itself pulls transcript content client-side."""
    html = _read()
    assert "transcript" not in html.lower()
