"""Thingstead fleet management — agent execution in managed fleets.

Implements Invariant 11: All agentic execution inside Thingstead fleets.

A ``ThingsteadFleet`` manages a pool of agents that execute pipeline stages
on behalf of the Corvusforge orchestrator.  Each agent is tracked via an
``AgentState``, and all execution is recorded as persistent ``MemoryShard``
entries in ``.openclaw-data/`` (Invariant 12).

When ``saoe-core`` is installed, the fleet integrates with ``AgentShim``
and ``ToolGate`` for SAOE-aware agent execution.  When unavailable,
lightweight stub implementations are used so the fleet remains functional
in standalone Corvusforge deployments.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from corvusforge.core.hasher import (
    compute_input_hash,
    compute_output_hash,
)
from corvusforge.thingstead.executors import (
    AgentExecutor,
    DefaultExecutor,
    DefaultToolGate,
    ToolGate,
)
from corvusforge.thingstead.memory import FleetMemory
from corvusforge.thingstead.models import ExecutionReceipt, FleetEvent

if TYPE_CHECKING:
    from corvusforge.core.orchestrator import Orchestrator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Try-import saoe-core agent primitives
# ---------------------------------------------------------------------------

_SAOE_AGENTS_AVAILABLE: bool = False
_AgentShim: Any = None
_ToolGate: Any = None

try:
    from saoe_core.agents import (  # type: ignore[import-untyped]
        AgentShim as _AgentShim,
    )
    from saoe_core.agents import (
        ToolGate as _ToolGate,  # noqa: F401 — future hook
    )

    _SAOE_AGENTS_AVAILABLE = True
    logger.debug("saoe_core.agents loaded — SAOE agent integration enabled.")
except ImportError:
    logger.info(
        "saoe_core.agents not found — using stub agent shims.  "
        "Install saoe-core for full Thingstead agent integration."
    )


# ---------------------------------------------------------------------------
# Stub fallbacks when saoe-core is not available
# ---------------------------------------------------------------------------

class _StubAgentShim:
    """Lightweight agent stub used when saoe-core is not installed.

    Provides the same call interface so fleet code does not need to
    branch on availability.
    """

    def __init__(self, agent_id: str, role: str) -> None:
        self.agent_id = agent_id
        self.role = role

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Pass-through execution — returns the payload as-is."""
        return {"status": "completed", "agent_id": self.agent_id, "payload": payload}


class _StubToolGate:
    """Lightweight tool-gate stub used when saoe-core is not installed."""

    def __init__(self) -> None:
        self.allowed_tools: list[str] = []

    def check(self, tool_name: str) -> bool:
        """Stub always permits."""
        return True


# ---------------------------------------------------------------------------
# Fleet configuration
# ---------------------------------------------------------------------------

class FleetConfig(BaseModel):
    """Immutable configuration for a Thingstead fleet.

    Parameters
    ----------
    fleet_name:
        Human-readable name for this fleet.
    max_agents:
        Maximum number of concurrent agents the fleet may spawn.
    data_dir:
        Path to the ``.openclaw-data/`` directory for persistent memory.
    enable_signing:
        Whether to sign execution receipts (requires crypto bridge).
    fleet_id:
        Unique identifier for this fleet instance (auto-generated).
    """

    model_config = ConfigDict(frozen=True)

    fleet_name: str = "default-fleet"
    max_agents: int = 8
    data_dir: Path = Path(".openclaw-data")
    enable_signing: bool = False
    fleet_id: str = Field(default_factory=lambda: uuid.uuid4().hex)


# ---------------------------------------------------------------------------
# Agent state
# ---------------------------------------------------------------------------

class AgentState(BaseModel):
    """Mutable tracking record for a single fleet agent.

    Tracks the agent's identity, assigned role and stage, current
    execution status, and timing information.

    Status values:
    - ``"idle"``: Agent created but not yet executing.
    - ``"executing"``: Agent is actively running a stage.
    - ``"completed"``: Agent finished its assigned stage successfully.
    - ``"failed"``: Agent encountered an error during execution.
    """

    model_config = ConfigDict(frozen=True)

    agent_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    role: str = "executor"
    stage_id: str = ""
    status: str = "idle"  # idle | executing | completed | failed
    assigned_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    completed_at: datetime | None = None


# ---------------------------------------------------------------------------
# Fleet
# ---------------------------------------------------------------------------

class ThingsteadFleet:
    """Manages a fleet of agents for pipeline stage execution.

    Enforces Invariant 11 (all agentic execution inside Thingstead fleets)
    by providing the sole entry point for agent-based stage processing.
    Execution records are persisted as memory shards in ``.openclaw-data/``
    (Invariant 12).

    Parameters
    ----------
    config:
        Fleet configuration.  Uses defaults if not provided.
    orchestrator:
        Optional reference to the Corvusforge orchestrator for
        integrated pipeline execution.
    """

    def __init__(
        self,
        config: FleetConfig | None = None,
        orchestrator: Orchestrator | None = None,
        executor_factory: Any | None = None,
        tool_gate: ToolGate | None = None,
    ) -> None:
        self.config = config or FleetConfig()
        self._orchestrator = orchestrator

        # Pluggable executor factory: (agent_id, role) -> AgentExecutor
        # Priority: saoe-core > user-provided > DefaultExecutor
        self._executor_factory = executor_factory

        # Pluggable tool gate
        # Priority: saoe-core > user-provided > DefaultToolGate
        self.tool_gate: ToolGate = tool_gate or DefaultToolGate()

        # Persistent memory store (Invariant 12)
        self.memory = FleetMemory(data_dir=self.config.data_dir)

        # Agent registry: agent_id -> AgentState
        self._agents: dict[str, AgentState] = {}

        # Fleet event log (in-memory, for observability)
        self._events: list[FleetEvent] = []

        logger.info(
            "ThingsteadFleet '%s' initialized (fleet_id=%s, max_agents=%d, "
            "saoe_agents=%s)",
            self.config.fleet_name,
            self.config.fleet_id,
            self.config.max_agents,
            _SAOE_AGENTS_AVAILABLE,
        )

    # ------------------------------------------------------------------
    # Agent lifecycle
    # ------------------------------------------------------------------

    def spawn_agent(self, role: str, stage_id: str) -> str:
        """Create a new agent assigned to a pipeline stage.

        Parameters
        ----------
        role:
            The agent's role (e.g. ``"executor"``, ``"reviewer"``).
        stage_id:
            The pipeline stage this agent is assigned to.

        Returns
        -------
        str
            The unique ``agent_id`` of the newly spawned agent.

        Raises
        ------
        RuntimeError
            If the fleet has reached its ``max_agents`` limit.
        """
        active_count = sum(
            1 for a in self._agents.values() if a.status in ("idle", "executing")
        )
        if active_count >= self.config.max_agents:
            raise RuntimeError(
                f"Fleet '{self.config.fleet_name}' has reached its max_agents "
                f"limit of {self.config.max_agents}."
            )

        agent_state = AgentState(role=role, stage_id=stage_id, status="idle")
        self._agents[agent_state.agent_id] = agent_state

        event = FleetEvent(
            fleet_id=self.config.fleet_id,
            event_type="agent_spawned",
            details={
                "agent_id": agent_state.agent_id,
                "role": role,
                "stage_id": stage_id,
            },
        )
        self._events.append(event)

        logger.debug(
            "Spawned agent %s (role=%s, stage=%s) in fleet %s",
            agent_state.agent_id,
            role,
            stage_id,
            self.config.fleet_id,
        )
        return agent_state.agent_id

    # ------------------------------------------------------------------
    # Stage execution
    # ------------------------------------------------------------------

    def execute_stage(
        self, stage_id: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute a pipeline stage within the fleet.

        Spawns an agent, runs the stage payload through it, records the
        execution to persistent memory, and returns the result with
        references to the memory shard(s) produced.

        Parameters
        ----------
        stage_id:
            The pipeline stage to execute.
        payload:
            Input data for the stage execution.

        Returns
        -------
        dict[str, Any]
            Execution result containing:
            - ``"status"``: ``"completed"`` or ``"failed"``
            - ``"agent_id"``: The agent that executed the stage
            - ``"stage_id"``: The stage that was executed
            - ``"result"``: The execution output
            - ``"memory_shards"``: List of shard IDs created
            - ``"receipt"``: The ``ExecutionReceipt`` as a dict
        """
        payload = payload or {}
        start_time = datetime.now(timezone.utc)

        # 1. Spawn an agent for this stage
        agent_id = self.spawn_agent(role="executor", stage_id=stage_id)

        # 2. Mark agent as executing
        self._agents[agent_id] = self._agents[agent_id].model_copy(
            update={"status": "executing"}
        )

        # 3. Execute through agent backend (priority: saoe > custom > default)
        try:
            executor: AgentExecutor
            if _SAOE_AGENTS_AVAILABLE and _AgentShim is not None:
                executor = _AgentShim(agent_id=agent_id, role="executor")
            elif self._executor_factory is not None:
                executor = self._executor_factory(agent_id, "executor")
            else:
                executor = DefaultExecutor(agent_id=agent_id, role="executor")
            result = executor.execute(payload)

            # 4. Record execution to persistent memory
            shard_ids = self._record_execution(agent_id, stage_id, payload, result)

            # 5. Compute hashes for the receipt
            end_time = datetime.now(timezone.utc)
            duration_ms = int((end_time - start_time).total_seconds() * 1000)
            input_hash = compute_input_hash(stage_id, payload)
            output_hash = compute_output_hash(stage_id, result)

            receipt = ExecutionReceipt(
                agent_id=agent_id,
                stage_id=stage_id,
                fleet_id=self.config.fleet_id,
                input_hash=input_hash,
                output_hash=output_hash,
                memory_shards=shard_ids,
                duration_ms=duration_ms,
            )

            # 6. Mark agent as completed
            self._agents[agent_id] = self._agents[agent_id].model_copy(
                update={
                    "status": "completed",
                    "completed_at": end_time,
                }
            )

            event = FleetEvent(
                fleet_id=self.config.fleet_id,
                event_type="agent_completed",
                details={
                    "agent_id": agent_id,
                    "stage_id": stage_id,
                    "duration_ms": duration_ms,
                    "shard_count": len(shard_ids),
                },
            )
            self._events.append(event)

            logger.info(
                "Stage %s completed by agent %s in %dms (%d shards)",
                stage_id,
                agent_id,
                duration_ms,
                len(shard_ids),
            )

            return {
                "status": "completed",
                "agent_id": agent_id,
                "stage_id": stage_id,
                "result": result,
                "memory_shards": shard_ids,
                "receipt": receipt.model_dump(mode="json"),
            }

        except Exception as exc:
            # Mark agent as failed
            self._agents[agent_id] = self._agents[agent_id].model_copy(
                update={
                    "status": "failed",
                    "completed_at": datetime.now(timezone.utc),
                }
            )

            event = FleetEvent(
                fleet_id=self.config.fleet_id,
                event_type="agent_failed",
                details={
                    "agent_id": agent_id,
                    "stage_id": stage_id,
                    "error": str(exc),
                },
            )
            self._events.append(event)

            logger.error(
                "Stage %s failed for agent %s: %s",
                stage_id,
                agent_id,
                exc,
            )
            raise

    # ------------------------------------------------------------------
    # Fleet status
    # ------------------------------------------------------------------

    def get_fleet_status(self) -> dict[str, Any]:
        """Return a summary of the fleet's current state.

        Returns
        -------
        dict[str, Any]
            Dictionary containing:
            - ``"fleet_id"``: The fleet's unique identifier.
            - ``"fleet_name"``: Human-readable fleet name.
            - ``"active_agents"``: Count of idle or executing agents.
            - ``"total_agents"``: Total agents spawned (all statuses).
            - ``"memory_shards"``: Total shards in persistent memory.
            - ``"saoe_available"``: Whether saoe-core agent integration is active.
        """
        active_count = sum(
            1 for a in self._agents.values() if a.status in ("idle", "executing")
        )
        return {
            "fleet_id": self.config.fleet_id,
            "fleet_name": self.config.fleet_name,
            "active_agents": active_count,
            "total_agents": len(self._agents),
            "memory_shards": self.memory.get_shard_count(),
            "saoe_available": _SAOE_AGENTS_AVAILABLE,
        }

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Shut down the fleet: persist memory and mark all agents completed.

        Persists the memory index to disk and transitions any non-terminal
        agents to ``"completed"`` status.  Emits ``fleet_shutdown`` and
        ``memory_persisted`` events.
        """
        # Persist memory index
        self.memory.persist_index()
        self._events.append(
            FleetEvent(
                fleet_id=self.config.fleet_id,
                event_type="memory_persisted",
                details={"shard_count": self.memory.get_shard_count()},
            )
        )

        # Mark all non-terminal agents as completed
        now = datetime.now(timezone.utc)
        for agent_id, state in list(self._agents.items()):
            if state.status in ("idle", "executing"):
                self._agents[agent_id] = state.model_copy(
                    update={"status": "completed", "completed_at": now}
                )

        self._events.append(
            FleetEvent(
                fleet_id=self.config.fleet_id,
                event_type="fleet_shutdown",
                details={
                    "total_agents": len(self._agents),
                    "memory_shards": self.memory.get_shard_count(),
                },
            )
        )

        logger.info(
            "Fleet '%s' (%s) shut down — %d agents, %d shards persisted.",
            self.config.fleet_name,
            self.config.fleet_id,
            len(self._agents),
            self.memory.get_shard_count(),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_execution(
        self,
        agent_id: str,
        stage_id: str,
        payload: dict[str, Any],
        result: dict[str, Any],
    ) -> list[str]:
        """Write execution data to FleetMemory as persistent shards.

        Creates two shards:
        1. An **input shard** recording the stage payload.
        2. An **output shard** recording the execution result.

        Parameters
        ----------
        agent_id:
            The agent that executed the stage.
        stage_id:
            The pipeline stage that was executed.
        payload:
            The input data provided to the stage.
        result:
            The output data produced by the stage.

        Returns
        -------
        list[str]
            The shard IDs of the input and output shards.
        """
        input_shard = self.memory.write_shard(
            fleet_id=self.config.fleet_id,
            agent_id=agent_id,
            stage_id=stage_id,
            content={"type": "input", "stage_id": stage_id, "payload": payload},
            tags=["input", stage_id],
        )

        output_shard = self.memory.write_shard(
            fleet_id=self.config.fleet_id,
            agent_id=agent_id,
            stage_id=stage_id,
            content={"type": "output", "stage_id": stage_id, "result": result},
            tags=["output", stage_id],
        )

        return [input_shard.shard_id, output_shard.shard_id]
