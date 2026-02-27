"""Unit tests for transport queue — SQLite persistence and local fallback.

Phase 3 of v0.4.0: Add SQLite-backed persistent queue as an alternative
to the volatile in-memory deque, enabling crash recovery and multi-process
message passing.

TDD: RED phase — these tests define the SQLite queue contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from corvusforge.bridge.transport import Transport, is_saoe_transport_available
from corvusforge.models.envelopes import WorkOrderEnvelope


def _make_envelope(run_id: str = "run-1") -> WorkOrderEnvelope:
    """Create a minimal test envelope (WorkOrder has work_specification)."""
    return WorkOrderEnvelope(
        run_id=run_id,
        source_node_id="test-node",
        destination_node_id="test-dest",
        stage_id="s0_intake",
        work_specification={"test": True},
    )


# ---------------------------------------------------------------------------
# Test: In-memory fallback (existing behavior, regression guard)
# ---------------------------------------------------------------------------


class TestLocalTransportInMemory:
    """In-memory deque transport must work as before (no db_path)."""

    def test_send_receive_round_trip(self):
        t = Transport(agent_id="test", max_local_queue=10)
        env = _make_envelope()
        eid = t.send(env)
        assert eid == env.envelope_id

        msg = t.receive()
        assert msg is not None

    def test_fifo_ordering(self):
        t = Transport(agent_id="test", max_local_queue=10)
        e1 = _make_envelope()
        e2 = _make_envelope()
        t.send(e1)
        t.send(e2)

        m1 = t.receive()
        m2 = t.receive()
        assert m1 is not None
        assert m2 is not None
        # First message out should contain first envelope's ID
        assert e1.envelope_id.encode() in m1
        assert e2.envelope_id.encode() in m2

    def test_receive_returns_none_when_empty(self):
        t = Transport(agent_id="test")
        assert t.receive() is None

    def test_drain_returns_all(self):
        t = Transport(agent_id="test", max_local_queue=10)
        for _ in range(3):
            t.send(_make_envelope())
        messages = t.drain()
        assert len(messages) == 3


# ---------------------------------------------------------------------------
# Test: SQLite-backed persistent queue
# ---------------------------------------------------------------------------


class TestLocalTransportSQLite:
    """SQLite-backed transport must persist across restart."""

    def test_send_receive_round_trip_sqlite(self, tmp_path: Path):
        db = tmp_path / "queue.db"
        t = Transport(agent_id="test", queue_db_path=db)
        env = _make_envelope()
        eid = t.send(env)
        assert eid == env.envelope_id

        msg = t.receive()
        assert msg is not None
        t.close()

    def test_fifo_ordering_sqlite(self, tmp_path: Path):
        db = tmp_path / "queue.db"
        t = Transport(agent_id="test", queue_db_path=db)
        e1 = _make_envelope()
        e2 = _make_envelope()
        t.send(e1)
        t.send(e2)

        m1 = t.receive()
        m2 = t.receive()
        assert m1 is not None and m2 is not None
        assert e1.envelope_id.encode() in m1
        assert e2.envelope_id.encode() in m2
        t.close()

    def test_persistence_across_restart(self, tmp_path: Path):
        """Messages survive transport close and re-open."""
        db = tmp_path / "queue.db"

        # Write
        env = _make_envelope()
        t1 = Transport(agent_id="test", queue_db_path=db)
        t1.send(env)
        t1.close()

        # Re-open and read
        t2 = Transport(agent_id="test", queue_db_path=db)
        msg = t2.receive()
        assert msg is not None
        # Verify it's the same envelope we sent
        assert env.envelope_id.encode() in msg
        t2.close()

    def test_bounded_at_max_depth_sqlite(self, tmp_path: Path):
        db = tmp_path / "queue.db"
        t = Transport(agent_id="test", queue_db_path=db, max_local_queue=3)
        for i in range(3):
            t.send(_make_envelope())

        # Queue is full — next send should raise
        with pytest.raises(Exception):
            t.send(_make_envelope())
        t.close()

    def test_drain_returns_all_sqlite(self, tmp_path: Path):
        db = tmp_path / "queue.db"
        t = Transport(agent_id="test", queue_db_path=db)
        for i in range(5):
            t.send(_make_envelope())
        messages = t.drain(max_messages=10)
        assert len(messages) == 5
        t.close()

    def test_close_sqlite(self, tmp_path: Path):
        db = tmp_path / "queue.db"
        t = Transport(agent_id="test", queue_db_path=db)
        t.send(_make_envelope())
        t.close()
        # After close, receive returns None (queue cleared)
        assert t.receive() is None

    def test_context_manager_sqlite(self, tmp_path: Path):
        db = tmp_path / "queue.db"
        with Transport(agent_id="test", queue_db_path=db) as t:
            t.send(_make_envelope())
            msg = t.receive()
            assert msg is not None

    def test_send_returns_envelope_id(self, tmp_path: Path):
        db = tmp_path / "queue.db"
        t = Transport(agent_id="test", queue_db_path=db)
        env = _make_envelope()
        eid = t.send(env)
        assert eid == env.envelope_id
        t.close()


# ---------------------------------------------------------------------------
# Test: Availability flags
# ---------------------------------------------------------------------------


class TestTransportAvailability:
    """Transport availability must reflect installed backends."""

    def test_transport_is_networked_false_without_saoe(self):
        t = Transport(agent_id="test")
        assert t.is_networked is False

    def test_saoe_transport_not_available(self):
        assert is_saoe_transport_available() is False
