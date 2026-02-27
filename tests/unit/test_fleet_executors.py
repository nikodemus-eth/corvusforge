"""Unit tests for pluggable agent executors and tool gates.

Phase 2 of v0.4.0: Promote stub agent shims to Protocol-based pluggable
backends, enabling custom executor and tool gate implementations.

TDD: RED phase — these tests define the desired Protocol contracts.
"""

from __future__ import annotations

from typing import Any

from corvusforge.thingstead.executors import (
    AgentExecutor,
    AllowlistToolGate,
    DefaultExecutor,
    DefaultToolGate,
    ToolGate,
)
from corvusforge.thingstead.fleet import FleetConfig, ThingsteadFleet

# ---------------------------------------------------------------------------
# Test: DefaultExecutor (promoted from _StubAgentShim)
# ---------------------------------------------------------------------------


class TestDefaultExecutor:
    """The default executor returns a completed status with the payload."""

    def test_default_executor_returns_completed_status(self):
        executor = DefaultExecutor(agent_id="test-agent", role="executor")
        result = executor.execute({"key": "value"})
        assert result["status"] == "completed"

    def test_default_executor_preserves_payload(self):
        executor = DefaultExecutor(agent_id="test-agent", role="executor")
        payload = {"stage_id": "s0", "data": [1, 2, 3]}
        result = executor.execute(payload)
        assert result["payload"] == payload

    def test_default_executor_includes_agent_id(self):
        executor = DefaultExecutor(agent_id="agent-42", role="reviewer")
        result = executor.execute({})
        assert result["agent_id"] == "agent-42"


# ---------------------------------------------------------------------------
# Test: DefaultToolGate (permits all tools)
# ---------------------------------------------------------------------------


class TestDefaultToolGate:
    """The default tool gate permits all tool invocations."""

    def test_default_tool_gate_allows_all(self):
        gate = DefaultToolGate()
        assert gate.check("any_tool") is True
        assert gate.check("another_tool") is True
        assert gate.check("") is True


# ---------------------------------------------------------------------------
# Test: AllowlistToolGate (blocks unlisted tools)
# ---------------------------------------------------------------------------


class TestAllowlistToolGate:
    """The allowlist tool gate only permits tools in its configured list."""

    def test_allowlist_tool_gate_blocks_unlisted(self):
        gate = AllowlistToolGate(allowed_tools=["read_file", "write_file"])
        assert gate.check("execute_shell") is False

    def test_allowlist_tool_gate_permits_listed(self):
        gate = AllowlistToolGate(allowed_tools=["read_file", "write_file"])
        assert gate.check("read_file") is True
        assert gate.check("write_file") is True

    def test_allowlist_empty_blocks_all(self):
        gate = AllowlistToolGate(allowed_tools=[])
        assert gate.check("any_tool") is False


# ---------------------------------------------------------------------------
# Test: Protocol compliance (structural typing)
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    """Executor and ToolGate implementations must satisfy their Protocols."""

    def test_executor_protocol_compliance(self):
        """DefaultExecutor must be a valid AgentExecutor."""
        executor: AgentExecutor = DefaultExecutor(agent_id="x", role="y")
        result = executor.execute({"test": True})
        assert isinstance(result, dict)

    def test_tool_gate_protocol_compliance(self):
        """DefaultToolGate must be a valid ToolGate."""
        gate: ToolGate = DefaultToolGate()
        assert isinstance(gate.check("tool"), bool)

    def test_allowlist_gate_protocol_compliance(self):
        """AllowlistToolGate must be a valid ToolGate."""
        gate: ToolGate = AllowlistToolGate(allowed_tools=["x"])
        assert isinstance(gate.check("x"), bool)


# ---------------------------------------------------------------------------
# Test: Fleet integration with pluggable backends
# ---------------------------------------------------------------------------


class TestFleetPluggableBackends:
    """Fleet must accept and use pluggable executor and tool gate backends."""

    def test_fleet_uses_registered_executor(self, tmp_path):
        """Fleet should use a custom executor factory when provided."""

        class TrackingExecutor:
            """Test executor that records calls."""

            calls: list[dict] = []

            def __init__(self, agent_id: str, role: str) -> None:
                self.agent_id = agent_id
                self.role = role

            def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
                TrackingExecutor.calls.append(payload)
                return {"status": "completed", "agent_id": self.agent_id, "payload": payload}

        TrackingExecutor.calls = []

        config = FleetConfig(fleet_name="test", data_dir=tmp_path / ".data")
        fleet = ThingsteadFleet(
            config,
            executor_factory=lambda aid, role: TrackingExecutor(aid, role),
        )
        fleet.execute_stage("s0", {"x": 1})
        assert len(TrackingExecutor.calls) == 1
        assert TrackingExecutor.calls[0] == {"x": 1}

    def test_fleet_uses_registered_tool_gate(self, tmp_path):
        """Fleet should expose the tool gate for pre-execution checks."""
        gate = AllowlistToolGate(allowed_tools=["read_file"])
        config = FleetConfig(fleet_name="test", data_dir=tmp_path / ".data")
        fleet = ThingsteadFleet(config, tool_gate=gate)

        assert fleet.tool_gate.check("read_file") is True
        assert fleet.tool_gate.check("execute_shell") is False

    def test_fleet_rejects_tool_when_gate_denies(self, tmp_path):
        """Fleet must check the tool gate before executing."""
        gate = AllowlistToolGate(allowed_tools=[])
        config = FleetConfig(fleet_name="test", data_dir=tmp_path / ".data")
        fleet = ThingsteadFleet(config, tool_gate=gate)

        # Tool gate should report denial
        assert fleet.tool_gate.check("dangerous_tool") is False
