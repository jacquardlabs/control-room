"""Generic attention detection: the seven-state taxonomy, hook-first with poll-fallback.

See `docs/specs/2026-07-11-t1-design.md` ("Notifications + acknowledge") and
DESIGN.md ("Semantic palette") for the taxonomy this package implements.
Discovery (`control_room.discovery`, `control_room.registry`) answers "does
this stream exist"; this package answers "what does it need from the human
right now" -- deliberately kept as a separate concern (see
`control_room/models.py`'s own module docstring).
"""

from __future__ import annotations
