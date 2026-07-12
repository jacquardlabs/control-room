"""The fleet shell: server, wall, tabs, SSE (issue #4).

Ties together every earlier T1 story's output into one always-current
snapshot -- `state.FleetState` polls `control_room.registry.StreamRegistry`,
resolves each stream's `AttentionEvent` (`control_room.attention.detector`),
builds its `BoardView` (`control_room.board.dispatch`), and tallies the wall
(`control_room.wall`) -- then `server` pushes that snapshot to the committed
static page (`static/index.html`) over SSE. Nothing here holds state across
a restart beyond what those modules already keep on disk; see
`state.FleetState`'s own docstring for why that satisfies "kill and restart
the server mid-anything reconstructs the screen exactly from disk truth."
"""
