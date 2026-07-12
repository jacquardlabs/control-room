"""Kind-specific stream discoverers: interactive sessions, jobs (workflow runs / background tasks).

Each discoverer answers "what does the CLI's own on-disk bookkeeping say
exists right now" -- liveness bookkeeping across polls belongs to
`control_room.registry.StreamRegistry`, not to these modules.
"""
