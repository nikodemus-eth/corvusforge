"""SinkDispatcher — routes events to ALL configured sinks (Invariant 9).

Every envelope dispatched through this module is fanned out to every
registered sink.  No event is silently dropped.  Sink failures are
logged but do not prevent delivery to remaining sinks.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from corvusforge.models.envelopes import EnvelopeBase

if TYPE_CHECKING:
    from corvusforge.routing.sinks import BaseSink

logger = logging.getLogger(__name__)


class SinkDispatchError(RuntimeError):
    """Raised when one or more sinks fail during dispatch."""


class SinkDispatcher:
    """Routes envelopes to ALL configured sinks.

    Invariant 9: every communication event can route to any and all
    configured sinks.  A failure in one sink does not block the others.

    Usage
    -----
    >>> dispatcher = SinkDispatcher()
    >>> dispatcher.register_sink(local_file_sink)
    >>> dispatcher.register_sink(artifact_store_sink)
    >>> dispatcher.dispatch(envelope)
    """

    def __init__(self) -> None:
        self._sinks: list[BaseSink] = []

    # ------------------------------------------------------------------
    # Sink management
    # ------------------------------------------------------------------

    def register_sink(self, sink: BaseSink) -> None:
        """Register a sink to receive dispatched envelopes.

        Sinks are called in registration order.  Duplicate registration
        of the same sink instance is silently ignored.
        """
        if sink not in self._sinks:
            self._sinks.append(sink)
            logger.info("Registered sink: %s", sink.sink_name)

    def unregister_sink(self, sink: BaseSink) -> None:
        """Remove a previously registered sink."""
        try:
            self._sinks.remove(sink)
            logger.info("Unregistered sink: %s", sink.sink_name)
        except ValueError:
            pass

    @property
    def registered_sinks(self) -> list[BaseSink]:
        """Return a copy of the registered sink list."""
        return list(self._sinks)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def dispatch(self, envelope: EnvelopeBase) -> list[str]:
        """Dispatch an envelope to ALL registered sinks.

        Returns a list of sink names that successfully received the
        envelope.  Failures are logged but do not halt delivery to
        remaining sinks.

        Raises
        ------
        SinkDispatchError
            If *all* sinks fail.  Individual failures are tolerated.
        """
        if not self._sinks:
            logger.warning(
                "No sinks registered — envelope %s dropped", envelope.envelope_id
            )
            return []

        succeeded: list[str] = []
        errors: list[tuple[str, Exception]] = []

        for sink in self._sinks:
            try:
                sink.accept(envelope)
                succeeded.append(sink.sink_name)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Sink %s failed for envelope %s: %s",
                    sink.sink_name,
                    envelope.envelope_id,
                    exc,
                )
                errors.append((sink.sink_name, exc))

        if errors and not succeeded:
            raise SinkDispatchError(
                f"All {len(errors)} sinks failed for envelope {envelope.envelope_id}: "
                + "; ".join(f"{name}: {exc}" for name, exc in errors)
            )

        if errors:
            logger.warning(
                "Envelope %s: %d/%d sinks succeeded, %d failed",
                envelope.envelope_id,
                len(succeeded),
                len(self._sinks),
                len(errors),
            )

        return succeeded

    def dispatch_batch(self, envelopes: list[EnvelopeBase]) -> dict[str, list[str]]:
        """Dispatch multiple envelopes, returning results keyed by envelope_id."""
        results: dict[str, list[str]] = {}
        for envelope in envelopes:
            try:
                results[envelope.envelope_id] = self.dispatch(envelope)
            except SinkDispatchError:
                results[envelope.envelope_id] = []
        return results
