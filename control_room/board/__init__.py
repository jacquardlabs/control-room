"""control-room's own schema-driven board renderer.

One schema (`control_room.board.models.BoardView`), two adapters
(`control_room.board.protocol_adapter` for streams that emit studious's
gate-ledger board protocol, `control_room.board.generic_adapter` for
everything else), one renderer (`control_room.board.render`) that never
branches on which adapter produced its input. `control_room.board.dispatch`
is the seam that picks an adapter per stream and degrades loudly, never
crashing, on a protocol it can't read.

DESIGN.md: "The board (per tab) -- control-room's own schema-driven
renderer for board-protocol streams (schema adopted from studious #98,
pixels are control-room's own)." Studious's board-ui rendering code is
never imported here -- only its on-disk ledger shape is read, as data.
"""

from __future__ import annotations
