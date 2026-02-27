"""Pluggable agent executor and tool gate backends for Thingstead fleets.

Defines the ``AgentExecutor`` and ``ToolGate`` Protocols that fleet backends
must satisfy, along with default implementations promoted from the original
stub shims.

Priority chain for agent execution:
1. **saoe-core** ``AgentShim`` / ``ToolGate`` — full SAOE agent integration.
2. **Custom backends** — user-provided Protocol implementations.
3. **DefaultExecutor** / **DefaultToolGate** — lightweight pass-through defaults.

v0.4.0: Phase 2 — promoted from inline stubs to Protocol-based pluggable system.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class AgentExecutor(Protocol):
    """Protocol for agent execution backends.

    Any object with an ``execute(payload) -> dict`` method satisfies this
    protocol.  saoe-core's ``AgentShim`` is compatible without modification.
    """

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute a stage payload and return the result.

        Parameters
        ----------
        payload:
            The input data for the stage.

        Returns
        -------
        dict[str, Any]
            Must include at minimum ``"status"`` (``"completed"`` or ``"failed"``).
        """
        ...


@runtime_checkable
class ToolGate(Protocol):
    """Protocol for tool access control gates.

    Any object with a ``check(tool_name) -> bool`` method satisfies this
    protocol.  saoe-core's ``ToolGate`` is compatible without modification.
    """

    def check(self, tool_name: str) -> bool:
        """Return ``True`` if the named tool is permitted, ``False`` otherwise."""
        ...


# ---------------------------------------------------------------------------
# Default implementations
# ---------------------------------------------------------------------------


class DefaultExecutor:
    """Lightweight pass-through executor (promoted from ``_StubAgentShim``).

    Returns the payload wrapped in a completed-status envelope.
    Suitable for development and testing; production should provide
    a real executor via the ``executor_factory`` parameter.
    """

    def __init__(self, agent_id: str, role: str) -> None:
        self.agent_id = agent_id
        self.role = role

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Pass-through execution — returns the payload as-is."""
        return {
            "status": "completed",
            "agent_id": self.agent_id,
            "payload": payload,
        }


class DefaultToolGate:
    """Permissive tool gate that allows all tool invocations.

    Suitable for development; production should use ``AllowlistToolGate``
    or a custom gate.
    """

    def check(self, tool_name: str) -> bool:
        """Always returns ``True`` — all tools permitted."""
        return True


class AllowlistToolGate:
    """Tool gate that only permits tools in a configured allowlist.

    Parameters
    ----------
    allowed_tools:
        List of tool names that are permitted.  Any tool not in this
        list will be denied.
    """

    def __init__(self, allowed_tools: list[str]) -> None:
        self._allowed: set[str] = set(allowed_tools)

    def check(self, tool_name: str) -> bool:
        """Return ``True`` if *tool_name* is in the allowlist."""
        return tool_name in self._allowed
