"""Pipeline orchestrator — the central coordinator for Corvusforge runs.

The Orchestrator wires together the RunLedger, StageMachine, PrerequisiteGraph,
ArtifactStore, WaiverManager, VersionPinner, and EnvelopeBus into a single
cohesive pipeline execution engine.

It delegates stage execution to registered stage handlers while enforcing
all 10 core invariants through its component subsystems.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from corvusforge.bridge.crypto_bridge import compute_trust_context
from corvusforge.config import ProdConfig
from corvusforge.core.artifact_store import ContentAddressedStore
from corvusforge.core.envelope_bus import EnvelopeBus
from corvusforge.core.hasher import compute_input_hash, compute_output_hash
from corvusforge.core.prerequisite_graph import PrerequisiteGraph
from corvusforge.core.production_guard import (
    enforce_production_constraints,
    production_waiver_signature_required,
)
from corvusforge.core.run_ledger import RunLedger
from corvusforge.core.stage_machine import StageMachine
from corvusforge.core.version_pinner import VersionPinner
from corvusforge.core.waiver_manager import WaiverManager
from corvusforge.models.config import PipelineConfig, RunConfig
from corvusforge.models.ledger import LedgerEntry
from corvusforge.models.stages import DEFAULT_STAGE_DEFINITIONS, StageState


class Orchestrator:
    """Central pipeline orchestrator.

    Creates and manages pipeline runs, delegates stage execution,
    and ensures all invariants are enforced.

    Parameters
    ----------
    config:
        Pipeline configuration. Uses defaults if not provided.
    run_id:
        Resume an existing run by ID. Creates new if None.
    """

    def __init__(
        self,
        config: PipelineConfig | None = None,
        run_id: str | None = None,
        *,
        prod_config: ProdConfig | None = None,
    ) -> None:
        self.config = config or PipelineConfig()
        self._prod_config = prod_config or ProdConfig()

        # Production guard — fails hard if production constraints are violated
        enforce_production_constraints(self._prod_config)

        # Core subsystems
        self.ledger = RunLedger(self.config.ledger_db_path)
        self.artifact_store = ContentAddressedStore(self.config.artifact_store_path)
        self.graph = PrerequisiteGraph(DEFAULT_STAGE_DEFINITIONS)
        self.stage_machine = StageMachine(self.ledger, self.graph)
        self.waiver_manager = WaiverManager(
            self.artifact_store,
            require_signature=production_waiver_signature_required(self._prod_config),
            waiver_verification_key=self._prod_config.waiver_signing_key,
        )
        self.version_pinner = VersionPinner(self.config.version_pin)
        self.envelope_bus = EnvelopeBus()

        # Run state
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        self.run_id = run_id or f"cf-{ts}-{uuid.uuid4().hex[:3]}"
        self.run_config: RunConfig | None = None

        # Trust context — key fingerprints recorded in every ledger entry
        self._trust_ctx = compute_trust_context(
            plugin_trust_root=getattr(self._prod_config, "plugin_trust_root", ""),
            waiver_signing_key=getattr(self._prod_config, "waiver_signing_key", ""),
            anchor_key=getattr(self._prod_config, "anchor_key", ""),
        )

        # Stage handler registry
        self._stage_handlers: dict[str, Callable] = {}

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    def start_run(self, prerequisites: list[dict[str, Any]] | None = None) -> RunConfig:
        """Initialize a new pipeline run.

        Creates the RunConfig, initializes all stage states,
        and records the intake entry in the ledger.
        """
        self.run_config = RunConfig(
            run_id=self.run_id,
            pipeline_config=self.config,
        )

        # Initialize all stages to NOT_STARTED
        self.stage_machine.initialize_run(self.run_id)

        # Record intake
        self.stage_machine.transition(
            self.run_id,
            "s0_intake",
            StageState.RUNNING,
            input_hash=compute_input_hash("s0_intake", {"prerequisites": prerequisites or []}),
            trust_context=self._trust_ctx,
        )
        self.stage_machine.transition(
            self.run_id,
            "s0_intake",
            StageState.PASSED,
            output_hash=compute_output_hash("s0_intake", {
                "run_id": self.run_id,
                "stage_count": len(DEFAULT_STAGE_DEFINITIONS),
            }),
            trust_context=self._trust_ctx,
        )

        return self.run_config

    def resume_run(self, run_id: str) -> dict[str, StageState]:
        """Resume an existing run from the ledger.

        Rebuilds state from ledger entries and returns current stage states.
        """
        self.run_id = run_id
        return self.stage_machine.get_all_states(run_id)

    # ------------------------------------------------------------------
    # Stage execution
    # ------------------------------------------------------------------

    def register_stage_handler(
        self, stage_id: str, handler: Callable[[str, dict[str, Any]], dict[str, Any]]
    ) -> None:
        """Register a handler function for a pipeline stage.

        The handler receives (run_id, payload) and returns a result dict.
        """
        self._stage_handlers[stage_id] = handler

    def execute_stage(
        self, stage_id: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute a pipeline stage through its registered handler.

        Lifecycle:
        1. Transition to RUNNING (prerequisites checked automatically)
        2. Compute input_hash
        3. Call handler
        4. Compute output_hash
        5. Store artifacts
        6. Transition to PASSED or FAILED
        7. Return result

        Returns the handler result dict.
        """
        payload = payload or {}
        input_hash = compute_input_hash(stage_id, payload)

        # 1. Transition to RUNNING
        self.stage_machine.transition(
            self.run_id, stage_id, StageState.RUNNING,
            input_hash=input_hash,
            trust_context=self._trust_ctx,
        )

        # 2. Execute handler
        handler = self._stage_handlers.get(stage_id)
        if handler:
            try:
                result = handler(self.run_id, payload)
            except Exception as exc:
                # Transition to FAILED on exception
                self.stage_machine.transition(
                    self.run_id, stage_id, StageState.FAILED,
                    input_hash=input_hash,
                    output_hash=compute_output_hash(stage_id, {"error": str(exc)}),
                    trust_context=self._trust_ctx,
                )
                raise
        else:
            # No handler registered — pass-through
            result = {"status": "passed", "note": "no handler registered"}

        # 3. Compute output hash and transition to PASSED
        output_hash = compute_output_hash(stage_id, result)
        artifact_refs = result.get("artifact_references", [])

        self.stage_machine.transition(
            self.run_id, stage_id, StageState.PASSED,
            input_hash=input_hash,
            output_hash=output_hash,
            artifact_references=artifact_refs,
            trust_context=self._trust_ctx,
        )

        return result

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def get_states(self) -> dict[str, StageState]:
        """Return current state of all stages."""
        return self.stage_machine.get_all_states(self.run_id)

    def get_stage_state(self, stage_id: str) -> StageState:
        """Return current state of a specific stage."""
        return self.stage_machine.get_current_state(self.run_id, stage_id)

    def get_run_entries(self) -> list[LedgerEntry]:
        """Return all ledger entries for the current run."""
        return self.ledger.get_run_entries(self.run_id)

    def verify_chain(self) -> bool:
        """Verify the hash chain integrity of the current run's ledger."""
        return self.ledger.verify_chain(self.run_id)
