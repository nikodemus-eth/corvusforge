"""Audit bridge — dual-write to Corvusforge RunLedger + saoe-core AuditLog.

Bridge boundary
---------------
Every state transition and envelope event is *always* written to the
Corvusforge ``RunLedger`` (append-only, hash-chained, SQLite-backed).

When ``saoe-core`` is installed, the same event is **also** written to
``saoe_core.audit.events_sqlite.AuditLog`` so that the broader SAOE audit
trail stays in sync.  When ``saoe-core`` is absent the saoe-side write is
silently skipped after a one-time warning at import.

Design rationale
~~~~~~~~~~~~~~~~
Corvusforge is the *source of truth* for its own pipeline runs.  The
saoe-core AuditLog is a *secondary consumer* — useful for cross-system
queries and compliance dashboards but never authoritative over the
Corvusforge RunLedger.  If the two ever diverge, the RunLedger wins.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from corvusforge.core.run_ledger import RunLedger
from corvusforge.models.envelopes import EnvelopeBase
from corvusforge.models.ledger import LedgerEntry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Try-import saoe_core.audit.events_sqlite.AuditLog
# ---------------------------------------------------------------------------

_SAOE_AUDIT_AVAILABLE: bool = False
_AuditLog: Any = None

try:
    from saoe_core.audit.events_sqlite import (
        AuditLog as _SaoeAuditLog,  # type: ignore[import-untyped]
    )

    _AuditLog = _SaoeAuditLog
    _SAOE_AUDIT_AVAILABLE = True
    logger.debug("saoe_core.audit.events_sqlite.AuditLog loaded — dual-write enabled.")
except ImportError:
    logger.warning(
        "saoe_core.audit.events_sqlite not found — audit_bridge will write "
        "to the Corvusforge RunLedger only.  Install saoe-core for dual-write."
    )


def is_saoe_audit_available() -> bool:
    """Return ``True`` if the saoe-core AuditLog backend is loaded."""
    return _SAOE_AUDIT_AVAILABLE


# ---------------------------------------------------------------------------
# Internal: saoe-side write helpers
# ---------------------------------------------------------------------------

def _write_to_saoe_audit(
    event_type: str,
    payload: dict[str, Any],
    *,
    saoe_audit_log: Any | None = None,
) -> None:
    """Best-effort write to the saoe-core AuditLog.

    Parameters
    ----------
    event_type:
        A string tag for the saoe-core event (e.g. ``"corvusforge.transition"``).
    payload:
        JSON-serializable dict written as the event body.
    saoe_audit_log:
        An optional pre-constructed ``AuditLog`` instance.  When ``None`` a
        new default instance is created (for simple use cases).
    """
    if not _SAOE_AUDIT_AVAILABLE or _AuditLog is None:
        return

    try:
        log_instance = saoe_audit_log if saoe_audit_log is not None else _AuditLog()
        log_instance.record(
            event_type=event_type,
            payload=payload,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except Exception:
        # Never let a saoe-side failure break the Corvusforge pipeline.
        logger.exception(
            "Failed to write event to saoe-core AuditLog — RunLedger entry "
            "is unaffected."
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_transition(
    entry: LedgerEntry,
    *,
    ledger: RunLedger,
    saoe_audit_log: Any | None = None,
) -> LedgerEntry:
    """Record a pipeline state transition to both audit destinations.

    This is the primary write path for all stage transitions.

    Parameters
    ----------
    entry:
        The ``LedgerEntry`` describing the transition.  The entry's
        ``previous_entry_hash`` and ``entry_hash`` will be computed by the
        ``RunLedger.append()`` call.
    ledger:
        The Corvusforge ``RunLedger`` instance (always required).
    saoe_audit_log:
        An optional saoe-core ``AuditLog`` instance for the secondary write.
        When ``None`` and saoe-core is available, a default instance is
        created automatically.

    Returns
    -------
    LedgerEntry
        The sealed entry (with computed hashes) as returned by
        ``RunLedger.append()``.
    """
    # --- Primary write: Corvusforge RunLedger (always) ---
    sealed_entry = ledger.append(entry)
    logger.debug(
        "RunLedger: appended entry %s for run=%s stage=%s (%s)",
        sealed_entry.entry_id,
        sealed_entry.run_id,
        sealed_entry.stage_id,
        sealed_entry.state_transition,
    )

    # --- Secondary write: saoe-core AuditLog (best-effort) ---
    _write_to_saoe_audit(
        event_type="corvusforge.transition",
        payload={
            "entry_id": sealed_entry.entry_id,
            "run_id": sealed_entry.run_id,
            "stage_id": sealed_entry.stage_id,
            "state_transition": sealed_entry.state_transition,
            "entry_hash": sealed_entry.entry_hash,
            "timestamp_utc": (
                sealed_entry.timestamp_utc.isoformat()
                if isinstance(sealed_entry.timestamp_utc, datetime)
                else str(sealed_entry.timestamp_utc)
            ),
        },
        saoe_audit_log=saoe_audit_log,
    )

    return sealed_entry


def record_envelope_event(
    envelope: EnvelopeBase,
    event_type: str,
    *,
    ledger: RunLedger | None = None,
    saoe_audit_log: Any | None = None,
) -> LedgerEntry | None:
    """Record an envelope-level event to both audit destinations.

    Use this when an envelope is sent, received, or rejected — events that
    should appear in the audit trail but may not correspond 1-to-1 with a
    stage state-machine transition.

    Parameters
    ----------
    envelope:
        The Corvusforge ``EnvelopeBase`` (or subclass) involved in the event.
    event_type:
        A descriptive tag such as ``"envelope.sent"``, ``"envelope.received"``,
        or ``"envelope.rejected"``.
    ledger:
        Optional ``RunLedger`` for the primary write.  When ``None`` the
        event is written only to the saoe-core AuditLog (if available).
    saoe_audit_log:
        Optional saoe-core ``AuditLog`` instance for the secondary write.

    Returns
    -------
    LedgerEntry | None
        The sealed ``LedgerEntry`` if a ``ledger`` was provided, else ``None``.
    """
    sealed_entry: LedgerEntry | None = None

    # Determine a reasonable stage_id — envelopes don't always carry one.
    stage_id: str = getattr(envelope, "stage_id", "") or "envelope"

    # --- Primary write: Corvusforge RunLedger (when a ledger is provided) ---
    if ledger is not None:
        entry = LedgerEntry(
            run_id=envelope.run_id,
            stage_id=stage_id,
            state_transition=f"envelope:{event_type}",
            input_hash=envelope.payload_hash,
        )
        sealed_entry = ledger.append(entry)
        logger.debug(
            "RunLedger: recorded envelope event %s for envelope=%s run=%s",
            event_type,
            envelope.envelope_id,
            envelope.run_id,
        )

    # --- Secondary write: saoe-core AuditLog (best-effort) ---
    _write_to_saoe_audit(
        event_type=f"corvusforge.envelope.{event_type}",
        payload={
            "envelope_id": envelope.envelope_id,
            "envelope_kind": envelope.envelope_kind.value,
            "run_id": envelope.run_id,
            "source_node_id": envelope.source_node_id,
            "destination_node_id": envelope.destination_node_id,
            "payload_hash": envelope.payload_hash,
            "event_type": event_type,
            "timestamp_utc": (
                envelope.timestamp_utc.isoformat()
                if isinstance(envelope.timestamp_utc, datetime)
                else str(envelope.timestamp_utc)
            ),
        },
        saoe_audit_log=saoe_audit_log,
    )

    return sealed_entry
