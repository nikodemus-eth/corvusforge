"""Adversarial tests — envelope validation and rejection.

These tests verify that:
1. Malformed JSON is rejected
2. Missing envelope_kind is rejected
3. Unknown envelope_kind is rejected
4. Invalid field types are rejected
5. The envelope bus only accepts valid Pydantic models
"""

from __future__ import annotations

import json

import pytest

from corvusforge.core.envelope_bus import EnvelopeBus, EnvelopeValidationError


class TestEnvelopeRejection:
    """Ensure invalid envelopes are caught and rejected."""

    @pytest.fixture
    def bus(self) -> EnvelopeBus:
        return EnvelopeBus()

    def test_reject_empty_bytes(self, bus):
        """Empty input must raise EnvelopeValidationError."""
        with pytest.raises(EnvelopeValidationError, match="Invalid JSON"):
            bus.receive(b"")

    def test_reject_malformed_json(self, bus):
        """Non-JSON input must raise EnvelopeValidationError."""
        with pytest.raises(EnvelopeValidationError, match="Invalid JSON"):
            bus.receive(b"this is not json {{{")

    def test_reject_missing_envelope_kind(self, bus):
        """JSON without envelope_kind must be rejected."""
        payload = json.dumps({"run_id": "test", "payload": "data"}).encode()
        with pytest.raises(EnvelopeValidationError, match="Missing envelope_kind"):
            bus.receive(payload)

    def test_reject_unknown_envelope_kind(self, bus):
        """JSON with an unknown envelope_kind must be rejected."""
        payload = json.dumps({
            "envelope_kind": "evil_payload",
            "run_id": "test",
        }).encode()
        with pytest.raises(EnvelopeValidationError, match="Unknown envelope_kind"):
            bus.receive(payload)

    def test_reject_valid_kind_invalid_fields(self, bus):
        """A known kind with missing required fields must be rejected."""
        payload = json.dumps({
            "envelope_kind": "work_order",
            # Missing all required fields for WorkOrderEnvelope
        }).encode()
        with pytest.raises(EnvelopeValidationError, match="validation failed"):
            bus.receive(payload)

    def test_reject_json_array(self, bus):
        """A JSON array (not object) must be rejected."""
        with pytest.raises(EnvelopeValidationError):
            bus.receive(b'[1, 2, 3]')

    def test_reject_null_envelope_kind(self, bus):
        """null envelope_kind must be rejected."""
        payload = json.dumps({"envelope_kind": None}).encode()
        with pytest.raises(EnvelopeValidationError, match="Missing envelope_kind"):
            bus.receive(payload)
