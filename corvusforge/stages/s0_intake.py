"""Stage 0 — Intake.

Creates the run identity, resolves the routing profile and interaction mode,
and produces the stage plan summary that drives all subsequent stages.

Outputs:
    run_id              — unique identifier for this pipeline run.
    monitor_link        — URL / path for the Build Monitor dashboard.
    routing_profile     — serialised RoutingProfile (sinks + interaction mode).
    interaction_mode    — resolved InteractionMode value.
    stage_plan_summary  — ordered list of stage definitions for this run.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, ClassVar

from corvusforge.core.hasher import content_address
from corvusforge.models.config import PipelineConfig, RunConfig
from corvusforge.models.routing import InteractionMode, RoutingProfile
from corvusforge.models.stages import DEFAULT_STAGE_DEFINITIONS, StageDefinition
from corvusforge.stages.base import BaseStage


class IntakeStage(BaseStage):
    """Stage 0: Intake — bootstraps a new pipeline run."""

    is_gate: ClassVar[bool] = False

    @property
    def stage_id(self) -> str:
        return "s0_intake"

    @property
    def display_name(self) -> str:
        return "Intake"

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def execute(self, run_context: dict[str, Any]) -> dict[str, Any]:
        """Create the run identity and resolve configuration.

        Reads optional overrides from *run_context*:
            ``pipeline_config`` — a ``PipelineConfig`` or dict.
            ``interaction_mode_override`` — force a specific mode.
            ``stage_plan_override`` — custom stage list.

        Returns a structured result dict consumed by all downstream stages.
        """
        # --- Resolve or create run_id -----------------------------------
        run_id: str = run_context.get("run_id", "")
        if not run_id:
            run_id = f"cf-{uuid.uuid4().hex[:12]}"
            run_context["run_id"] = run_id

        # --- Resolve pipeline configuration -----------------------------
        raw_config = run_context.get("pipeline_config")
        if isinstance(raw_config, PipelineConfig):
            pipeline_config = raw_config
        elif isinstance(raw_config, dict):
            pipeline_config = PipelineConfig(**raw_config)
        else:
            pipeline_config = PipelineConfig()

        # --- Resolve routing profile ------------------------------------
        routing_profile: RoutingProfile = pipeline_config.routing_profile

        # Allow an explicit interaction-mode override
        mode_override = run_context.get("interaction_mode_override")
        if mode_override is not None:
            if isinstance(mode_override, str):
                mode_override = InteractionMode(mode_override)
            routing_profile = routing_profile.model_copy(
                update={"interaction_mode": mode_override}
            )

        # --- Resolve stage plan -----------------------------------------
        stage_plan_override = run_context.get("stage_plan_override")
        if stage_plan_override is not None:
            stage_plan: list[StageDefinition] = [
                sd if isinstance(sd, StageDefinition) else StageDefinition(**sd)
                for sd in stage_plan_override
            ]
        else:
            stage_plan = list(DEFAULT_STAGE_DEFINITIONS)

        # --- Build stage plan summary -----------------------------------
        stage_plan_summary: list[dict[str, Any]] = [
            {
                "stage_id": sd.stage_id,
                "display_name": sd.display_name,
                "ordinal": sd.ordinal,
                "prerequisites": list(sd.prerequisites),
                "is_mandatory_gate": sd.is_mandatory_gate,
            }
            for sd in stage_plan
        ]

        # --- Build monitor link -----------------------------------------
        monitor_link = (
            f"file://{pipeline_config.ledger_db_path.parent}/monitor.html"
            f"?run_id={run_id}"
        )

        # --- Build RunConfig and store on context for downstream --------
        run_config = RunConfig(
            run_id=run_id,
            pipeline_config=pipeline_config,
            stage_plan=stage_plan,
        )
        run_context["run_config"] = run_config

        # --- Content-address the run configuration as an artifact -------
        config_ref = content_address(run_config.model_dump(mode="json"))

        # --- Timestamp ---------------------------------------------------
        created_at = datetime.now(timezone.utc).isoformat()

        return {
            "run_id": run_id,
            "monitor_link": monitor_link,
            "routing_profile": routing_profile.model_dump(mode="json"),
            "interaction_mode": routing_profile.interaction_mode.value,
            "stage_plan_summary": stage_plan_summary,
            "config_artifact_ref": config_ref,
            "created_at": created_at,
            "_artifact_refs": [config_ref],
        }
