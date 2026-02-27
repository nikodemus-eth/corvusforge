"""Tests for EnvelopeBus — validation, serialization, dispatch."""

from __future__ import annotations

import json

import pytest

from corvusforge.core.envelope_bus import EnvelopeBus, EnvelopeValidationError
from corvusforge.models.envelopes import (
    EnvelopeKind,
    EventEnvelope,
    WorkOrderEnvelope,
)


class TestEnvelopeBus:
    def test_prepare_sets_payload_hash(self):
        bus = EnvelopeBus()
        env = WorkOrderEnvelope(
            run_id="test-run",
            source_node_id="a",
            destination_node_id="b",
            stage_id="s0_intake",
        )
        prepared = bus.prepare(env)
        assert prepared.payload_hash != ""

    def test_send_returns_envelope_id(self):
        bus = EnvelopeBus()
        env = WorkOrderEnvelope(
            run_id="test-run",
            source_node_id="a",
            destination_node_id="b",
            stage_id="s0_intake",
        )
        eid = bus.send(env)
        assert eid == env.envelope_id

    def test_send_dispatches_to_handlers(self):
        bus = EnvelopeBus()
        received = []
        bus.register_handler(EnvelopeKind.WORK_ORDER, lambda e: received.append(e))

        env = WorkOrderEnvelope(
            run_id="test-run",
            source_node_id="a",
            destination_node_id="b",
            stage_id="s0",
        )
        bus.send(env)
        assert len(received) == 1

    def test_receive_valid_json(self):
        bus = EnvelopeBus()
        data = {
            "schema_version": "2026-02",
            "envelope_id": "test-id",
            "run_id": "test-run",
            "source_node_id": "a",
            "destination_node_id": "b",
            "envelope_kind": "event",
            "event_type": "stage_transition",
            "stage_id": "s0",
            "timestamp_utc": "2026-02-27T00:00:00Z",
        }
        env = bus.receive(json.dumps(data))
        assert isinstance(env, EventEnvelope)
        assert env.event_type == "stage_transition"

    def test_receive_invalid_json(self):
        bus = EnvelopeBus()
        with pytest.raises(EnvelopeValidationError, match="Invalid JSON"):
            bus.receive(b"not json")

    def test_receive_unknown_kind(self):
        bus = EnvelopeBus()
        data = json.dumps({"envelope_kind": "unknown_type"})
        with pytest.raises(EnvelopeValidationError, match="Unknown envelope_kind"):
            bus.receive(data)

    def test_receive_missing_kind(self):
        bus = EnvelopeBus()
        data = json.dumps({"run_id": "test"})
        with pytest.raises(EnvelopeValidationError, match="Missing envelope_kind"):
            bus.receive(data)

    def test_serialize_canonical(self):
        env = WorkOrderEnvelope(
            run_id="test",
            source_node_id="a",
            destination_node_id="b",
            stage_id="s0",
        )
        raw = EnvelopeBus.serialize(env)
        # Canonical JSON: sorted keys, no whitespace
        parsed = json.loads(raw)
        assert parsed["run_id"] == "test"
