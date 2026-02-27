"""Pipeline and run configuration models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from corvusforge.models.routing import RoutingProfile
from corvusforge.models.stages import DEFAULT_STAGE_DEFINITIONS, StageDefinition
from corvusforge.models.versioning import VersionPin


class PipelineConfig(BaseModel):
    """Project-level configuration for the Corvusforge pipeline.

    Loaded from corvusforge.toml or pyproject.toml [tool.corvusforge].
    """

    model_config = ConfigDict(frozen=True)

    project_name: str = "corvusforge"
    saoe_core_path: Path | None = None  # path to saoe-mvp/saoe-core
    artifact_store_path: Path = Path(".corvusforge/artifacts")
    ledger_db_path: Path = Path(".corvusforge/ledger.db")
    routing_profile: RoutingProfile = RoutingProfile()
    version_pin: VersionPin = VersionPin()


class RunConfig(BaseModel):
    """Per-run configuration, created at Stage 0 (Intake)."""

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(default_factory=lambda: f"cf-{uuid.uuid4().hex[:12]}")
    pipeline_config: PipelineConfig = PipelineConfig()
    stage_plan: list[StageDefinition] = Field(
        default_factory=lambda: list(DEFAULT_STAGE_DEFINITIONS)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
