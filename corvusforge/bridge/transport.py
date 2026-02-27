"""Transport bridge — wraps saoe-openclaw AgentShim for envelope I/O.

Bridge boundary
---------------
``saoe_openclaw.shim.AgentShim`` provides a channel-based send/receive
interface for SAOE agents.  This module wraps it behind a simplified
``Transport`` class that Corvusforge orchestration code can depend on
without importing saoe-openclaw directly.

When ``saoe-openclaw`` is not installed, ``Transport`` operates in
**local-only mode** with two queue backends:

1. **SQLite queue** (``queue_db_path`` provided): Persistent, crash-safe,
   survives transport restart.  Recommended for production.
2. **In-memory deque** (``queue_db_path`` is None): Volatile, bounded,
   suitable for tests and single-process deployments.

The local queue is bounded (default 1024 messages) to prevent unbounded
growth during long pipeline runs.

v0.4.0: Added SQLite-backed persistent queue (Phase 3).
"""

from __future__ import annotations

import collections
import logging
import sqlite3
from pathlib import Path
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
        "saoe_openclaw.shim not found — Transport will use a local queue.  "
        "Install saoe-openclaw for networked SAOE transport."
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
        Maximum depth of the local queue (both in-memory and SQLite).
        Ignored when the real ``AgentShim`` is in use.
    queue_db_path:
        Path to a SQLite database file for persistent queue storage.
        When ``None``, an in-memory deque is used (volatile).
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
        queue_db_path: Path | None = None,
        **shim_kwargs: Any,
    ) -> None:
        self._agent_id = agent_id
        self._channel = channel
        self._max_local_queue = max_local_queue
        self._shim: Any | None = None

        # SQLite queue backend (Tier 2a — persistent local)
        self._db: sqlite3.Connection | None = None
        if queue_db_path is not None:
            self._db = sqlite3.connect(str(queue_db_path))
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS queue ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  payload BLOB NOT NULL,"
                "  created_at TEXT DEFAULT (datetime('now'))"
                ")"
            )
            self._db.commit()
            logger.info(
                "Transport: using SQLite queue at %s (max_depth=%d).",
                queue_db_path,
                max_local_queue,
            )

        # In-memory deque fallback (Tier 2b — volatile local)
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
        elif self._db is None:
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
        """Number of messages waiting in the local queue."""
        if self._db is not None:
            row = self._db.execute("SELECT COUNT(*) FROM queue").fetchone()
            return row[0] if row else 0
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

        # --- Local queue (SQLite or in-memory) ---
        return self._local_send(payload_bytes, envelope.envelope_id)

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

        # --- Local queue (SQLite or in-memory) ---
        return self._local_receive()

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

        # Close SQLite connection if open
        if self._db is not None:
            self._db.close()
            self._db = None

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
        if self.is_networked:
            backend = "AgentShim"
        elif self._db is not None:
            backend = "sqlite-queue"
        else:
            backend = "local-queue"
        return (
            f"Transport(agent_id={self._agent_id!r}, "
            f"channel={self._channel!r}, backend={backend})"
        )

    # ------------------------------------------------------------------
    # Internal: local queue operations
    # ------------------------------------------------------------------

    def _local_send(self, payload_bytes: bytes, envelope_id: str) -> str:
        """Enqueue a message in the local queue (SQLite or in-memory)."""
        # SQLite queue
        if self._db is not None:
            depth = self._db.execute("SELECT COUNT(*) FROM queue").fetchone()[0]
            if depth >= self._max_local_queue:
                raise TransportError(
                    f"Local transport queue is full "
                    f"(depth={depth}).  "
                    f"Envelope {envelope_id} dropped."
                )
            self._db.execute(
                "INSERT INTO queue (payload) VALUES (?)",
                (payload_bytes,),
            )
            self._db.commit()
            logger.debug(
                "Transport.send: queued envelope %s in SQLite (depth=%d).",
                envelope_id,
                depth + 1,
            )
            return envelope_id

        # In-memory deque
        if len(self._local_queue) >= (self._local_queue.maxlen or 1024):
            raise TransportError(
                f"Local transport queue is full "
                f"(depth={len(self._local_queue)}).  "
                f"Envelope {envelope_id} dropped."
            )

        self._local_queue.append(payload_bytes)
        logger.debug(
            "Transport.send: queued envelope %s locally (depth=%d).",
            envelope_id,
            len(self._local_queue),
        )
        return envelope_id

    def _local_receive(self) -> bytes | None:
        """Dequeue the oldest message from the local queue."""
        # SQLite queue
        if self._db is not None:
            row = self._db.execute(
                "SELECT id, payload FROM queue ORDER BY id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            row_id, payload = row
            self._db.execute("DELETE FROM queue WHERE id = ?", (row_id,))
            self._db.commit()
            logger.debug(
                "Transport.receive: dequeued message from SQLite (id=%d).",
                row_id,
            )
            return bytes(payload) if not isinstance(payload, bytes) else payload

        # In-memory deque
        if self._local_queue:
            msg_bytes = self._local_queue.popleft()
            logger.debug(
                "Transport.receive: dequeued local message (remaining=%d).",
                len(self._local_queue),
            )
            return msg_bytes

        return None
