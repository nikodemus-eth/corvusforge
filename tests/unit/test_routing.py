"""Unit tests for SinkDispatcher and LocalFileSink.

Phase 6D of v0.4.0: Tests dispatcher fan-out, partial failure, all-sinks-fail,
and LocalFileSink write/read round-trip.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from corvusforge.models.envelopes import EnvelopeBase, EnvelopeKind, EventEnvelope
from corvusforge.routing.dispatcher import SinkDispatchError, SinkDispatcher
from corvusforge.routing.sinks import BaseSink
from corvusforge.routing.sinks.local_file import LocalFileSink


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event_envelope(run_id: str = "test-run-001") -> EventEnvelope:
    """Create a minimal EventEnvelope for testing."""
    return EventEnvelope(
        run_id=run_id,
        source_node_id="src-node",
        destination_node_id="dst-node",
        stage_id="s0_intake",
        event_type="test_event",
        event_data={"key": "value"},
    )


class _SuccessSink:
    """A sink that always succeeds."""

    def __init__(self, name: str = "success_sink") -> None:
        self._name = name
        self.received: list[EnvelopeBase] = []

    @property
    def sink_name(self) -> str:
        return self._name

    def accept(self, envelope: EnvelopeBase) -> None:
        self.received.append(envelope)


class _FailingSink:
    """A sink that always raises."""

    @property
    def sink_name(self) -> str:
        return "failing_sink"

    def accept(self, envelope: EnvelopeBase) -> None:
        raise RuntimeError("Sink failure for testing")


# ---------------------------------------------------------------------------
# Test: SinkDispatcher
# ---------------------------------------------------------------------------


class TestSinkDispatcher:
    """SinkDispatcher must fan out to all sinks, tolerating partial failure."""

    def test_dispatch_to_single_sink(self):
        """A single registered sink should receive the envelope."""
        dispatcher = SinkDispatcher()
        sink = _SuccessSink()
        dispatcher.register_sink(sink)

        envelope = _make_event_envelope()
        succeeded = dispatcher.dispatch(envelope)

        assert succeeded == ["success_sink"]
        assert len(sink.received) == 1

    def test_dispatch_to_multiple_sinks(self):
        """All registered sinks receive the envelope."""
        dispatcher = SinkDispatcher()
        sink_a = _SuccessSink("sink_a")
        sink_b = _SuccessSink("sink_b")
        dispatcher.register_sink(sink_a)
        dispatcher.register_sink(sink_b)

        envelope = _make_event_envelope()
        succeeded = dispatcher.dispatch(envelope)

        assert sorted(succeeded) == ["sink_a", "sink_b"]
        assert len(sink_a.received) == 1
        assert len(sink_b.received) == 1

    def test_dispatch_no_sinks_returns_empty(self):
        """No registered sinks should return empty list (no error)."""
        dispatcher = SinkDispatcher()
        envelope = _make_event_envelope()
        succeeded = dispatcher.dispatch(envelope)
        assert succeeded == []

    def test_dispatch_partial_failure(self):
        """One sink failure should not block delivery to other sinks."""
        dispatcher = SinkDispatcher()
        good_sink = _SuccessSink("good")
        bad_sink = _FailingSink()
        dispatcher.register_sink(good_sink)
        dispatcher.register_sink(bad_sink)

        envelope = _make_event_envelope()
        succeeded = dispatcher.dispatch(envelope)

        assert succeeded == ["good"]
        assert len(good_sink.received) == 1

    def test_dispatch_all_fail_raises(self):
        """When ALL sinks fail, SinkDispatchError must be raised."""
        dispatcher = SinkDispatcher()
        dispatcher.register_sink(_FailingSink())

        envelope = _make_event_envelope()
        with pytest.raises(SinkDispatchError, match="All .* sinks failed"):
            dispatcher.dispatch(envelope)

    def test_register_duplicate_ignored(self):
        """Registering the same sink instance twice should be idempotent."""
        dispatcher = SinkDispatcher()
        sink = _SuccessSink()
        dispatcher.register_sink(sink)
        dispatcher.register_sink(sink)

        assert len(dispatcher.registered_sinks) == 1

    def test_unregister_sink(self):
        """Unregistered sink should no longer receive envelopes."""
        dispatcher = SinkDispatcher()
        sink = _SuccessSink()
        dispatcher.register_sink(sink)
        dispatcher.unregister_sink(sink)

        assert len(dispatcher.registered_sinks) == 0

    def test_dispatch_batch(self):
        """dispatch_batch should handle multiple envelopes."""
        dispatcher = SinkDispatcher()
        sink = _SuccessSink()
        dispatcher.register_sink(sink)

        envelopes = [_make_event_envelope(f"run-{i}") for i in range(3)]
        results = dispatcher.dispatch_batch(envelopes)

        assert len(results) == 3
        assert len(sink.received) == 3


# ---------------------------------------------------------------------------
# Test: LocalFileSink
# ---------------------------------------------------------------------------


class TestLocalFileSink:
    """LocalFileSink must write and read envelope JSON files correctly."""

    def test_accept_writes_json_file(self, tmp_path: Path):
        """Accepting an envelope should create a JSON file."""
        sink = LocalFileSink(base_path=tmp_path / "events")
        envelope = _make_event_envelope()

        sink.accept(envelope)

        files = list((tmp_path / "events").rglob("*.json"))
        assert len(files) == 1

    def test_accept_file_layout(self, tmp_path: Path):
        """File should be at {base}/{run_id}/{stage_id}/{envelope_id}.json."""
        sink = LocalFileSink(base_path=tmp_path / "events")
        envelope = _make_event_envelope("layout-run")

        sink.accept(envelope)

        # EventEnvelope has stage_id="s0_intake" from _make_event_envelope
        expected_dir = tmp_path / "events" / "layout-run" / "s0_intake"
        assert expected_dir.is_dir()
        files = list(expected_dir.glob("*.json"))
        assert len(files) == 1

    def test_read_event_round_trip(self, tmp_path: Path):
        """Written event should be readable and contain correct data."""
        sink = LocalFileSink(base_path=tmp_path / "events")
        envelope = _make_event_envelope("roundtrip-run")

        sink.accept(envelope)

        files = sink.list_events("roundtrip-run")
        assert len(files) == 1

        data = sink.read_event(files[0])
        assert data["run_id"] == "roundtrip-run"
        assert data["envelope_kind"] == EnvelopeKind.EVENT.value

    def test_list_events_empty_run(self, tmp_path: Path):
        """Listing events for a non-existent run should return empty list."""
        sink = LocalFileSink(base_path=tmp_path / "events")
        assert sink.list_events("nonexistent-run") == []

    def test_sink_protocol_compliance(self, tmp_path: Path):
        """LocalFileSink should satisfy the BaseSink protocol."""
        sink = LocalFileSink(base_path=tmp_path / "events")
        assert isinstance(sink, BaseSink)
        assert sink.sink_name == "local_file"
