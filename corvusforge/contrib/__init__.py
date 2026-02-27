"""Corvusforge contrib — learning mode hooks and user contribution tracking.

This package provides hooks for marking decision points in the pipeline
where user input shapes outcomes, and a decision registry for tracking
those user-supplied decisions.

The contrib system enables "learning mode" — a mode where the pipeline
pauses at key decision points to let the operator observe, understand,
and influence the pipeline's behavior.  Every decision is recorded for
audit and replay.
"""
