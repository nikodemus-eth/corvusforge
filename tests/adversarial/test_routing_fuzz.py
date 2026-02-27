"""Adversarial tests — routing dispatcher resilience under failure.

These tests verify that:
1. Sink exceptions don't prevent delivery to other sinks
2. All-sinks-fail raises SinkDispatchError
3. No-sinks-registered doesn't crash
4. Batch dispatch handles mixed success/failure
5. Sinks that throw various exception types are handled gracefully
"""

from __future__ import annotations

import pytest

from corvusforge.models.envelopes import EnvelopeBase, EnvelopeKind
from corvusforge.routing.dispatcher import SinkDispatcher, SinkDispatchError

# ---------------------------------------------------------------------------
# Test sinks
# ---------------------------------------------------------------------------

class GoodSink:
    """A sink that always succeeds."""

    def __init__(self, name: str = "good-sink"):
        self._name = name
        self.received: list[EnvelopeBase] = []

    @property
    def sink_name(self) -> str:
        return self._name

    def accept(self, envelope: EnvelopeBase) -> None:
        self.received.append(envelope)


class ExplodingSink:
    """A sink that always throws."""

    def __init__(self, name: str = "exploding-sink", exc_type: type = RuntimeError):
        self._name = name
        self._exc_type = exc_type

    @property
    def sink_name(self) -> str:
        return self._name

    def accept(self, envelope: EnvelopeBase) -> None:
        raise self._exc_type(f"{self._name} exploded!")


class SlowExplodingSink:
    """A sink that succeeds N times then explodes."""

    def __init__(self, name: str = "slow-bomb", fail_after: int = 2):
        self._name = name
        self._fail_after = fail_after
        self._count = 0

    @property
    def sink_name(self) -> str:
        return self._name

    def accept(self, envelope: EnvelopeBase) -> None:
        self._count += 1
        if self._count > self._fail_after:
            raise RuntimeError(f"{self._name} failed on call {self._count}")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_envelope() -> EnvelopeBase:
    """Create a minimal valid envelope for testing."""
    return EnvelopeBase(
        run_id="test-run",
        source_node_id="test-source",
        destination_node_id="test-dest",
        envelope_kind=EnvelopeKind.EVENT,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSinkFailureIsolation:
    """Invariant 9: delivery to other sinks must continue despite failures."""

    def test_one_exploding_sink_doesnt_block_good_sink(self):
        """A failing sink must not prevent delivery to healthy sinks."""
        dispatcher = SinkDispatcher()
        good = GoodSink("reliable")
        bad = ExplodingSink("unreliable")
        dispatcher.register_sink(good)
        dispatcher.register_sink(bad)

        envelope = _make_envelope()
        succeeded = dispatcher.dispatch(envelope)

        assert "reliable" in succeeded
        assert "unreliable" not in succeeded
        assert len(good.received) == 1

    def test_all_sinks_fail_raises_dispatch_error(self):
        """When ALL sinks fail, SinkDispatchError must be raised."""
        dispatcher = SinkDispatcher()
        dispatcher.register_sink(ExplodingSink("bad-1"))
        dispatcher.register_sink(ExplodingSink("bad-2"))

        with pytest.raises(SinkDispatchError, match="All.*sinks failed"):
            dispatcher.dispatch(_make_envelope())

    def test_no_sinks_registered_returns_empty(self):
        """Dispatching with no sinks must return empty list, not crash."""
        dispatcher = SinkDispatcher()
        result = dispatcher.dispatch(_make_envelope())
        assert result == []

    def test_various_exception_types_handled(self):
        """Sinks throwing different exception types must all be caught."""
        dispatcher = SinkDispatcher()
        good = GoodSink("survivor")
        dispatcher.register_sink(ExplodingSink("type-err", TypeError))
        dispatcher.register_sink(ExplodingSink("value-err", ValueError))
        dispatcher.register_sink(ExplodingSink("os-err", OSError))
        dispatcher.register_sink(good)

        succeeded = dispatcher.dispatch(_make_envelope())
        assert "survivor" in succeeded
        assert len(good.received) == 1

    def test_duplicate_sink_registration_ignored(self):
        """Registering the same sink instance twice is silently ignored."""
        dispatcher = SinkDispatcher()
        sink = GoodSink("once")
        dispatcher.register_sink(sink)
        dispatcher.register_sink(sink)
        assert len(dispatcher.registered_sinks) == 1


class TestBatchDispatchResilience:
    """Test batch dispatch under mixed conditions."""

    def test_batch_with_intermittent_sink_failure(self):
        """A sink that fails mid-batch must not corrupt other envelopes."""
        dispatcher = SinkDispatcher()
        good = GoodSink("steady")
        flaky = SlowExplodingSink("flaky", fail_after=2)
        dispatcher.register_sink(good)
        dispatcher.register_sink(flaky)

        envelopes = [_make_envelope() for _ in range(5)]
        results = dispatcher.dispatch_batch(envelopes)

        # All 5 should have "steady" as successful
        for eid, sinks in results.items():
            assert "steady" in sinks

        # Good sink should have received all 5
        assert len(good.received) == 5

    def test_batch_all_sinks_fail_records_empty_lists(self):
        """Batch dispatch with all-fail sinks records empty results."""
        dispatcher = SinkDispatcher()
        dispatcher.register_sink(ExplodingSink("doomed"))

        envelopes = [_make_envelope() for _ in range(3)]
        results = dispatcher.dispatch_batch(envelopes)

        for eid, sinks in results.items():
            assert sinks == []
