"""Transport bridge — wraps saoe-openclaw AgentShim for envelope I/O.

Bridge boundary
---------------
``saoe_openclaw.shim.AgentShim`` provides a channel-based send/receive
interface for SAOE agents.  This module wraps it behind a simplified
``Transport`` class that Corvusforge orchestration code can depend on
without importing saoe-openclaw directly.

When ``saoe-openclaw`` is not installed, ``Transport`` operates in
**local-only mode**: sent envelopes are placed into an in-memory queue
that ``receive()`` drains.  This allows Corvusforge's stage machine and
orchestrator to run end-to-end in tests and single-process deployments
without any external dependencies.

The local queue is bounded (default 1024 messages) to prevent unbounded
memory growth during long pipeline runs.
"""

from __future__ import annotations

import collections
import logging
from typing import Any

from corvusforge.core.hasher import canonical_json_bytes
from corvusforge.models.envelopes import EnvelopeBase

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Try-import saoe_openclaw.shim.AgentShim
# ---------------------------------------------------------------------------

_SAOE_SHIM_AVAILABLE: bool = False
_AgentShim: Any = None

try:
    from saoe_openclaw.shim import AgentShim as _SaoeAgentShim  # type: ignore[import-untyped]

    _AgentShim = _SaoeAgentShim
    _SAOE_SHIM_AVAILABLE = True
    logger.debug("saoe_openclaw.shim.AgentShim loaded — using SAOE transport.")
except ImportError:
    logger.warning(
        "saoe_openclaw.shim not found — Transport will use a local in-memory "
        "queue.  Install saoe-openclaw for networked SAOE transport."
    )


def is_saoe_transport_available() -> bool:
    """Return ``True`` if the saoe-openclaw AgentShim backend is loaded."""
    return _SAOE_SHIM_AVAILABLE


# ---------------------------------------------------------------------------
# Transport class
# ---------------------------------------------------------------------------

class TransportError(RuntimeError):
    """Raised when a transport-level operation fails."""


class Transport:
    """Unified send/receive interface for Corvusforge envelopes.

    Parameters
    ----------
    agent_id:
        Identifier for this agent / node in the SAOE mesh.  Used as the
        ``source_node_id`` when the shim registers with the network.
    channel:
        Logical channel name (e.g. ``"corvusforge-pipeline"``).  Only
        meaningful when saoe-openclaw is available.
    max_local_queue:
        Maximum depth of the in-memory fallback queue.  Ignored when the
        real ``AgentShim`` is in use.
    shim_kwargs:
        Extra keyword arguments forwarded to the ``AgentShim`` constructor
        (e.g. connection URIs, TLS settings).
    """

    def __init__(
        self,
        agent_id: str = "corvusforge",
        channel: str = "corvusforge-pipeline",
        *,
        max_local_queue: int = 1024,
        **shim_kwargs: Any,
    ) -> None:
        self._agent_id = agent_id
        self._channel = channel
        self._shim: Any | None = None
        self._local_queue: collections.deque[bytes] = collections.deque(
            maxlen=max_local_queue
        )

        if _SAOE_SHIM_AVAILABLE and _AgentShim is not None:
            try:
                self._shim = _AgentShim(
                    agent_id=agent_id,
                    channel=channel,
                    **shim_kwargs,
                )
                logger.info(
                    "Transport: connected AgentShim agent_id=%s channel=%s",
                    agent_id,
                    channel,
                )
            except Exception:
                logger.exception(
                    "Transport: AgentShim construction failed — falling back "
                    "to local queue."
                )
                self._shim = None
        else:
            logger.info(
                "Transport: using local in-memory queue (max_depth=%d).",
                max_local_queue,
            )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def agent_id(self) -> str:
        """The agent / node identifier for this transport."""
        return self._agent_id

    @property
    def channel(self) -> str:
        """The logical channel name."""
        return self._channel

    @property
    def is_networked(self) -> bool:
        """``True`` if backed by a real AgentShim, ``False`` if local-only."""
        return self._shim is not None

    @property
    def local_queue_depth(self) -> int:
        """Number of messages waiting in the local fallback queue."""
        return len(self._local_queue)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send(self, envelope: EnvelopeBase) -> str:
        """Serialize and send a Corvusforge envelope.

        Parameters
        ----------
        envelope:
            Any ``EnvelopeBase`` subclass to transmit.

        Returns
        -------
        str
            The ``envelope_id`` of the sent message.

        Raises
        ------
        TransportError
            If the networked send fails *and* the local queue is also full.
        """
        payload_bytes = canonical_json_bytes(
            envelope.model_dump(mode="json")
        )

        if self._shim is not None:
            try:
                self._shim.send(
                    channel=self._channel,
                    payload=payload_bytes,
                    metadata={
                        "envelope_id": envelope.envelope_id,
                        "envelope_kind": envelope.envelope_kind.value,
                        "run_id": envelope.run_id,
                    },
                )
                logger.debug(
                    "Transport.send: dispatched envelope %s via AgentShim.",
                    envelope.envelope_id,
                )
                return envelope.envelope_id
            except Exception as exc:
                logger.warning(
                    "Transport.send: AgentShim.send() failed (%s) — "
                    "falling back to local queue.",
                    exc,
                )
                # Fall through to local queue as a resilience measure.

        # --- Local fallback ---
        if len(self._local_queue) >= (self._local_queue.maxlen or 1024):
            raise TransportError(
                f"Local transport queue is full "
                f"(depth={len(self._local_queue)}).  "
                f"Envelope {envelope.envelope_id} dropped."
            )

        self._local_queue.append(payload_bytes)
        logger.debug(
            "Transport.send: queued envelope %s locally (depth=%d).",
            envelope.envelope_id,
            len(self._local_queue),
        )
        return envelope.envelope_id

    def receive(self, *, timeout_seconds: float = 0.0) -> bytes | None:
        """Receive the next raw envelope payload.

        Parameters
        ----------
        timeout_seconds:
            How long to wait for a message.  ``0`` means non-blocking.
            Only meaningful when backed by a real ``AgentShim``.

        Returns
        -------
        bytes | None
            The canonical JSON bytes of the envelope, or ``None`` if no
            message is available within the timeout.
        """
        if self._shim is not None:
            try:
                msg = self._shim.receive(
                    channel=self._channel,
                    timeout=timeout_seconds,
                )
                if msg is not None:
                    # AgentShim may return bytes or a wrapper; normalise.
                    payload = (
                        msg.payload
                        if hasattr(msg, "payload")
                        else msg
                    )
                    if isinstance(payload, str):
                        payload = payload.encode("utf-8")
                    logger.debug("Transport.receive: got message via AgentShim.")
                    return payload
                return None
            except Exception as exc:
                logger.warning(
                    "Transport.receive: AgentShim.receive() failed (%s) — "
                    "draining local queue instead.",
                    exc,
                )
                # Fall through to local queue.

        # --- Local fallback ---
        if self._local_queue:
            msg_bytes = self._local_queue.popleft()
            logger.debug(
                "Transport.receive: dequeued local message (remaining=%d).",
                len(self._local_queue),
            )
            return msg_bytes

        return None

    def drain(self, *, max_messages: int = 100) -> list[bytes]:
        """Drain up to *max_messages* from the transport.

        Convenience wrapper around repeated ``receive()`` calls.

        Returns
        -------
        list[bytes]
            A list of raw envelope payloads (may be empty).
        """
        messages: list[bytes] = []
        for _ in range(max_messages):
            msg = self.receive(timeout_seconds=0.0)
            if msg is None:
                break
            messages.append(msg)
        return messages

    def close(self) -> None:
        """Shut down the transport, releasing any external resources."""
        if self._shim is not None:
            try:
                if hasattr(self._shim, "close"):
                    self._shim.close()
                elif hasattr(self._shim, "disconnect"):
                    self._shim.disconnect()
            except Exception:
                logger.exception("Transport.close: error shutting down AgentShim.")
            finally:
                self._shim = None
        self._local_queue.clear()
        logger.info("Transport: closed (agent_id=%s).", self._agent_id)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> Transport:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        backend = "AgentShim" if self.is_networked else "local-queue"
        return (
            f"Transport(agent_id={self._agent_id!r}, "
            f"channel={self._channel!r}, backend={backend})"
        )
