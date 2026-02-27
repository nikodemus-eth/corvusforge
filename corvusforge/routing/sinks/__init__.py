"""Sink protocol and registry for Corvusforge event routing.

All sinks implement the ``BaseSink`` protocol: a ``sink_name`` property
and an ``accept(envelope)`` method.  The dispatcher calls ``accept``
on every registered sink for every dispatched envelope.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from corvusforge.models.envelopes import EnvelopeBase


@runtime_checkable
class BaseSink(Protocol):
    """Protocol that every Corvusforge sink must implement.

    Sinks are pluggable targets that receive validated envelopes from the
    SinkDispatcher.  Each sink decides how to persist, forward, or
    transform the envelope data.

    Attributes
    ----------
    sink_name : str
        A unique human-readable identifier for this sink instance
        (e.g. ``"local_file"``, ``"artifact_store"``).
    """

    @property
    def sink_name(self) -> str:
        """Return the unique name of this sink."""
        ...

    def accept(self, envelope: EnvelopeBase) -> None:
        """Accept and process an envelope.

        Implementations must not raise for transient errors that should
        not block other sinks.  Critical failures may raise; the
        dispatcher will log them and continue to the next sink.

        Parameters
        ----------
        envelope:
            The validated envelope to process.
        """
        ...
