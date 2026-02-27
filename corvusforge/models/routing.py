"""Routing and interaction models — sink dispatch + interaction modes."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict


class InteractionMode(str, Enum):
    """How the pipeline interacts with the operator during a run."""

    INTERACTIVE = "interactive"
    ASYNC = "async"
    FAIL_FAST = "fail_fast"


class RoutingSink(BaseModel):
    """A single notification/artifact sink configuration.

    Sinks are pluggable targets for event routing. Every communication
    event can route to any and all configured sinks (Invariant 9).
    """

    model_config = ConfigDict(frozen=True)

    sink_type: str  # "local_file", "artifact_store", "telegram", "email"
    config: dict[str, Any] = {}
    enabled: bool = True


class RoutingProfile(BaseModel):
    """Per-run routing configuration.

    Defines the interaction mode and the set of sinks that receive events.
    """

    model_config = ConfigDict(frozen=True)

    interaction_mode: InteractionMode = InteractionMode.INTERACTIVE
    sinks: list[RoutingSink] = [
        RoutingSink(sink_type="local_file"),
        RoutingSink(sink_type="artifact_store"),
    ]


class PauseState(BaseModel):
    """Represents a paused run's state."""

    model_config = ConfigDict(frozen=True)

    pause_reason: str
    paused_since: str  # ISO 8601
    resume_deadline: str | None = None  # ISO 8601, optional
