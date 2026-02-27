"""Additional Pydantic models for Thingstead fleet integration.

Provides frozen data models for fleet snapshots, agent assignments,
execution receipts, and fleet lifecycle events.

All models are immutable (frozen=True) and use Pydantic v2 conventions
consistent with the rest of Corvusforge.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FleetSnapshot(BaseModel):
    """Point-in-time snapshot of a Thingstead fleet's state.

    Captures the fleet's identity, agent count, memory shard count,
    and currently active pipeline stages.
    """

    model_config = ConfigDict(frozen=True)

    fleet_id: str
    fleet_name: str
    agent_count: int
    shard_count: int
    active_stages: list[str] = Field(default_factory=list)
    snapshot_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class AgentAssignment(BaseModel):
    """Immutable record of an agent assigned to a fleet and pipeline stage.

    Used by the fleet to track which agent handles which stage,
    with optional priority for scheduling.
    """

    model_config = ConfigDict(frozen=True)

    agent_id: str
    fleet_id: str
    stage_id: str
    role: str
    priority: int = 0


class ExecutionReceipt(BaseModel):
    """Immutable receipt produced after a fleet agent completes stage execution.

    Contains content-addressed hashes of both input and output, references
    to any memory shards written during execution, and timing information.
    This receipt is the auditable proof that execution occurred within the fleet.
    """

    model_config = ConfigDict(frozen=True)

    receipt_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex
    )
    agent_id: str
    stage_id: str
    fleet_id: str
    input_hash: str
    output_hash: str
    memory_shards: list[str] = Field(default_factory=list)
    duration_ms: int
    completed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class FleetEvent(BaseModel):
    """Immutable event emitted during fleet lifecycle operations.

    Tracks agent spawning, completion, failure, fleet shutdown,
    and memory persistence events for audit and observability.

    Valid event_type values:
    - ``"agent_spawned"``: A new agent was created in the fleet.
    - ``"agent_completed"``: An agent finished its assigned stage.
    - ``"agent_failed"``: An agent encountered an error during execution.
    - ``"fleet_shutdown"``: The fleet was shut down and all agents terminated.
    - ``"memory_persisted"``: The fleet memory index was persisted to disk.
    """

    model_config = ConfigDict(frozen=True)

    event_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex
    )
    fleet_id: str
    # "agent_spawned" | "agent_completed" | "agent_failed"
    # | "fleet_shutdown" | "memory_persisted"
    event_type: str
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
