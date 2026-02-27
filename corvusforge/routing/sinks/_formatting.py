"""Shared formatting helpers for Corvusforge notification sinks.

Extracts common envelope-to-text patterns used across email, Telegram,
and future sinks.  Keeps sink implementations DRY and consistent.
"""

from __future__ import annotations

from corvusforge.models.envelopes import EnvelopeBase


def format_kind_label(envelope: EnvelopeBase) -> str:
    """Return a human-readable label for the envelope kind.

    Examples
    --------
    >>> from corvusforge.models.envelopes import EventEnvelope
    >>> env = EventEnvelope(
    ...     run_id="r", source_node_id="s", destination_node_id="d",
    ...     stage_id="s0", event_type="test",
    ... )
    >>> format_kind_label(env)
    'Event'
    """
    return envelope.envelope_kind.value.replace("_", " ").title()


def extract_stage_id(envelope: EnvelopeBase, default: str = "N/A") -> str:
    """Extract ``stage_id`` from an envelope, falling back to *default*.

    Not every envelope type carries a ``stage_id`` field, so we use
    ``getattr`` with a default to avoid ``AttributeError``.
    """
    return getattr(envelope, "stage_id", None) or default


def extract_detail_lines(envelope: EnvelopeBase) -> list[str]:
    """Extract kind-specific detail lines from an envelope.

    Returns a list of ``"Label: value"`` strings for optional fields
    like ``event_type``, ``error_message``, ``question``, and
    ``artifact_ref``.  Only non-absent fields are included.
    """
    lines: list[str] = []
    if hasattr(envelope, "event_type"):
        lines.append(f"Event Type: {envelope.event_type}")
    if hasattr(envelope, "error_message"):
        lines.append(f"Error: {envelope.error_message}")
    if hasattr(envelope, "question"):
        lines.append(f"Question: {envelope.question}")
    if hasattr(envelope, "artifact_ref"):
        lines.append(f"Artifact: {envelope.artifact_ref}")
    return lines
