"""Corvusforge Build Monitor — pure read-only projection over the Run Ledger.

The Build Monitor NEVER maintains its own state.  Every call re-reads from
the ledger.  It is a projection, not a source of truth.

Modules
-------
projection
    ``MonitorProjection`` reads the ledger and produces ``MonitorSnapshot``
    Pydantic models — a frozen, point-in-time view of a pipeline run.
renderer
    ``MonitorRenderer`` turns ``MonitorSnapshot`` into Rich renderables
    for terminal display, including continuous ``Rich.Live`` mode.
"""
