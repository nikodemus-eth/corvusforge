"""Unit tests for the audit bridge — dual-write with graceful saoe degradation.

Phase 6A of v0.4.0: Fills coverage gaps for audit_bridge.py.
Exercises record_transition, record_envelope_event, and saoe-unavailable paths.
"""

from __future__ import annotations

from pathlib import Path

from corvusforge.bridge.audit_bridge import (
    is_saoe_audit_available,
    record_envelope_event,
    record_transition,
)
from corvusforge.core.run_ledger import RunLedger
from corvusforge.models.envelopes import EventEnvelope
from corvusforge.models.ledger import LedgerEntry

# ---------------------------------------------------------------------------
# Test: saoe availability
# ---------------------------------------------------------------------------


class TestSaoeAuditAvailability:
    """saoe-core is not installed, so audit bridge uses RunLedger only."""

    def test_is_saoe_audit_available_false(self):
        """saoe-core is not installed — availability must be False."""
        assert is_saoe_audit_available() is False


# ---------------------------------------------------------------------------
# Test: record_transition
# ---------------------------------------------------------------------------


class TestRecordTransition:
    """Dual-write record_transition must always succeed via RunLedger."""

    def test_record_transition_appends_to_ledger(self, tmp_path: Path):
        """record_transition should append the entry and return it sealed."""
        ledger = RunLedger(tmp_path / "ledger.db")
        entry = LedgerEntry(
            run_id="test-run-001",
            stage_id="s0_intake",
            state_transition="NOT_STARTED->RUNNING",
            input_hash="abc123",
        )
        sealed = record_transition(entry, ledger=ledger)

        assert sealed.entry_id != ""
        assert sealed.run_id == "test-run-001"
        assert sealed.stage_id == "s0_intake"
        assert sealed.entry_hash != ""

    def test_record_transition_returns_sealed_entry(self, tmp_path: Path):
        """The sealed entry must have computed hashes (from RunLedger.append)."""
        ledger = RunLedger(tmp_path / "ledger.db")
        entry = LedgerEntry(
            run_id="test-run-002",
            stage_id="s1_prerequisites",
            state_transition="NOT_STARTED->RUNNING",
        )
        sealed = record_transition(entry, ledger=ledger)

        # RunLedger.append fills in entry_hash
        assert sealed.entry_hash is not None
        assert sealed.entry_hash != ""

    def test_record_transition_graceful_without_saoe(self, tmp_path: Path):
        """When saoe-core absent, record_transition must not raise."""
        ledger = RunLedger(tmp_path / "ledger.db")
        entry = LedgerEntry(
            run_id="test-run-003",
            stage_id="s2_environment",
            state_transition="RUNNING->PASSED",
            input_hash="def456",
            output_hash="ghi789",
        )
        # Should not raise even though saoe-core is unavailable
        sealed = record_transition(entry, ledger=ledger, saoe_audit_log=None)
        assert sealed.run_id == "test-run-003"


# ---------------------------------------------------------------------------
# Test: record_envelope_event
# ---------------------------------------------------------------------------


class TestRecordEnvelopeEvent:
    """record_envelope_event must handle both with-ledger and without-ledger."""

    def _make_event_envelope(self) -> EventEnvelope:
        return EventEnvelope(
            run_id="test-run-evt-001",
            source_node_id="node-a",
            destination_node_id="node-b",
            stage_id="s0_intake",
            event_type="test_event",
            event_data={"key": "value"},
        )

    def test_record_envelope_event_with_ledger(self, tmp_path: Path):
        """With a ledger, should write a LedgerEntry and return it."""
        ledger = RunLedger(tmp_path / "ledger.db")
        envelope = self._make_event_envelope()

        sealed = record_envelope_event(
            envelope, "sent", ledger=ledger
        )
        assert sealed is not None
        assert sealed.run_id == "test-run-evt-001"
        assert "envelope:sent" in sealed.state_transition

    def test_record_envelope_event_without_ledger(self):
        """Without a ledger, should return None (saoe-only path)."""
        envelope = self._make_event_envelope()

        result = record_envelope_event(envelope, "received", ledger=None)
        assert result is None
