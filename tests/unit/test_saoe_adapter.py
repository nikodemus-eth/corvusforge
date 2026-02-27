"""Unit tests for SAOE adapter — local serialization and SATL unavailability.

Phase 4 of v0.4.0: Add to_local() and from_local() methods that provide
signed envelope serialization using PyNaCl, without requiring saoe-core.

TDD: RED phase — these tests define the local serialization contract.
"""

from __future__ import annotations

import pytest

from corvusforge.bridge.crypto_bridge import generate_keypair
from corvusforge.bridge.saoe_adapter import (
    SaoeAdapterError,
    SaoeAdapterUnavailableError,
    from_local,
    from_satl,
    to_local,
    to_satl,
)
from corvusforge.models.envelopes import EnvelopeKind, WorkOrderEnvelope


def _make_envelope() -> WorkOrderEnvelope:
    """Create a test work order envelope."""
    return WorkOrderEnvelope(
        run_id="run-test-1",
        source_node_id="node-a",
        destination_node_id="node-b",
        stage_id="s0_intake",
        work_specification={"task": "test"},
    )


# ---------------------------------------------------------------------------
# Test: SATL unavailability (saoe-core not installed)
# ---------------------------------------------------------------------------


class TestSatlUnavailable:
    """to_satl and from_satl must raise when saoe-core is absent."""

    def test_to_satl_raises_when_saoe_unavailable(self):
        env = _make_envelope()
        with pytest.raises(SaoeAdapterUnavailableError):
            to_satl(env, signing_key="fake", template_ref="test/v1")

    def test_from_satl_raises_when_saoe_unavailable(self):
        with pytest.raises(SaoeAdapterUnavailableError):
            from_satl({"payload": {}})


# ---------------------------------------------------------------------------
# Test: Local serialization (no saoe-core needed, uses PyNaCl)
# ---------------------------------------------------------------------------


class TestLocalSerialization:
    """to_local / from_local must sign and verify with real Ed25519."""

    def test_to_local_serializes_envelope_with_signature(self):
        priv, pub = generate_keypair()
        env = _make_envelope()
        data = to_local(env, signing_key=priv)

        assert isinstance(data, dict)
        assert "payload" in data
        assert "payload_hash" in data
        assert "signature" in data
        assert "envelope_kind" in data
        # Signature must be a real Ed25519 sig (128 hex chars)
        assert len(data["signature"]) == 128

    def test_from_local_reconstitutes_envelope(self):
        priv, pub = generate_keypair()
        env = _make_envelope()
        data = to_local(env, signing_key=priv)

        reconstituted = from_local(data)
        assert reconstituted.envelope_id == env.envelope_id
        assert reconstituted.run_id == env.run_id
        assert reconstituted.envelope_kind == EnvelopeKind.WORK_ORDER

    def test_from_local_rejects_invalid_kind(self):
        priv, pub = generate_keypair()
        env = _make_envelope()
        data = to_local(env, signing_key=priv)

        # Tamper with the envelope_kind
        data["envelope_kind"] = "invalid_kind"
        with pytest.raises(SaoeAdapterError, match="Unknown envelope_kind"):
            from_local(data)

    def test_from_local_rejects_missing_kind(self):
        priv, pub = generate_keypair()
        env = _make_envelope()
        data = to_local(env, signing_key=priv)

        # Remove the envelope_kind
        del data["envelope_kind"]
        with pytest.raises(SaoeAdapterError, match="envelope_kind"):
            from_local(data)

    def test_local_round_trip_preserves_all_fields(self):
        priv, pub = generate_keypair()
        env = _make_envelope()
        data = to_local(env, signing_key=priv)
        reconstituted = from_local(data)

        assert reconstituted.source_node_id == env.source_node_id
        assert reconstituted.destination_node_id == env.destination_node_id
        assert reconstituted.stage_id == env.stage_id
        assert reconstituted.work_specification == env.work_specification
        assert reconstituted.schema_version == env.schema_version
