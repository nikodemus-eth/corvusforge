"""Unit tests for the Orchestrator.

Phase 6F of v0.4.0: Tests construction, start_run, handler registration,
execute_stage, and trust context.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from corvusforge.config import ProdConfig
from corvusforge.core.orchestrator import Orchestrator
from corvusforge.models.config import PipelineConfig
from corvusforge.models.stages import StageState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(tmp_path: Path) -> PipelineConfig:
    """Create a PipelineConfig with temp paths."""
    return PipelineConfig(
        ledger_db_path=tmp_path / "ledger.db",
        artifact_store_path=tmp_path / "artifacts",
    )


# ---------------------------------------------------------------------------
# Test: Construction
# ---------------------------------------------------------------------------


class TestOrchestratorConstruction:
    """Orchestrator must initialize all subsystems."""

    def test_construction_creates_subsystems(self, tmp_path: Path):
        """Default construction should create ledger, artifact store, etc."""
        orch = Orchestrator(config=_make_config(tmp_path))

        assert orch.ledger is not None
        assert orch.artifact_store is not None
        assert orch.stage_machine is not None
        assert orch.graph is not None
        assert orch.waiver_manager is not None
        assert orch.version_pinner is not None
        assert orch.envelope_bus is not None

    def test_run_id_auto_generated(self, tmp_path: Path):
        """Without explicit run_id, one should be generated."""
        orch = Orchestrator(config=_make_config(tmp_path))
        assert orch.run_id.startswith("cf-")

    def test_run_id_explicit(self, tmp_path: Path):
        """Explicit run_id should be used as-is."""
        orch = Orchestrator(config=_make_config(tmp_path), run_id="explicit-id")
        assert orch.run_id == "explicit-id"


# ---------------------------------------------------------------------------
# Test: start_run
# ---------------------------------------------------------------------------


class TestOrchestratorStartRun:
    """start_run must initialize stages and record intake."""

    def test_start_run_returns_run_config(self, tmp_path: Path):
        """start_run should return a RunConfig."""
        orch = Orchestrator(config=_make_config(tmp_path))
        rc = orch.start_run()

        assert rc is not None
        assert rc.run_id == orch.run_id

    def test_start_run_records_intake_passed(self, tmp_path: Path):
        """After start_run, s0_intake should be PASSED."""
        orch = Orchestrator(config=_make_config(tmp_path))
        orch.start_run()

        state = orch.get_stage_state("s0_intake")
        assert state == StageState.PASSED

    def test_start_run_populates_ledger(self, tmp_path: Path):
        """start_run should produce ledger entries for the intake."""
        orch = Orchestrator(config=_make_config(tmp_path))
        orch.start_run()

        entries = orch.get_run_entries()
        # At least 2 entries: RUNNING and PASSED for s0_intake
        assert len(entries) >= 2


# ---------------------------------------------------------------------------
# Test: Handler registration and execution
# ---------------------------------------------------------------------------


class TestOrchestratorExecution:
    """Stage handlers must be called and results recorded."""

    def test_register_and_execute_stage(self, tmp_path: Path):
        """A registered handler should be called during execute_stage."""
        orch = Orchestrator(config=_make_config(tmp_path))
        orch.start_run()

        handler_called = False

        def test_handler(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
            nonlocal handler_called
            handler_called = True
            return {"status": "passed", "data": "test-result"}

        orch.register_stage_handler("s1_prerequisites", test_handler)
        result = orch.execute_stage("s1_prerequisites", {"input": "test"})

        assert handler_called
        assert result["status"] == "passed"

    def test_execute_stage_no_handler(self, tmp_path: Path):
        """Stage with no handler should pass-through."""
        orch = Orchestrator(config=_make_config(tmp_path))
        orch.start_run()

        result = orch.execute_stage("s1_prerequisites")
        assert result["status"] == "passed"
        assert "no handler" in result.get("note", "")

    def test_execute_stage_transitions_to_passed(self, tmp_path: Path):
        """Successful execution should transition stage to PASSED."""
        orch = Orchestrator(config=_make_config(tmp_path))
        orch.start_run()
        orch.execute_stage("s1_prerequisites")

        state = orch.get_stage_state("s1_prerequisites")
        assert state == StageState.PASSED


# ---------------------------------------------------------------------------
# Test: Trust context
# ---------------------------------------------------------------------------


class TestOrchestratorTrustContext:
    """Trust context must be populated from ProdConfig."""

    def test_trust_context_populated(self, tmp_path: Path):
        """Orchestrator should compute trust context from prod_config."""
        orch = Orchestrator(config=_make_config(tmp_path))
        # The trust context is computed in __init__
        assert orch._trust_ctx is not None
        assert "plugin_trust_root_fp" in orch._trust_ctx
        assert "waiver_signing_key_fp" in orch._trust_ctx
        assert "anchor_key_fp" in orch._trust_ctx
