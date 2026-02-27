"""Unit tests for BaseStage lifecycle enforcement.

Phase 6C of v0.4.0: Tests the abstract base stage, prerequisite validation,
input/output hashing, recording, and the gate flag.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from corvusforge.models.stages import StageState
from corvusforge.stages.base import (
    BaseStage,
    StageExecutionError,
    StagePrerequisiteError,
)

# ---------------------------------------------------------------------------
# Concrete test stage implementations
# ---------------------------------------------------------------------------


class _PassingStage(BaseStage):
    """A minimal stage that always passes."""

    @property
    def stage_id(self) -> str:
        return "test_passing"

    @property
    def display_name(self) -> str:
        return "Passing Test Stage"

    def execute(self, run_context: dict[str, Any]) -> dict[str, Any]:
        return {"status": "passed", "message": "hello from passing stage"}


class _FailingStage(BaseStage):
    """A stage that always raises during execute."""

    @property
    def stage_id(self) -> str:
        return "test_failing"

    @property
    def display_name(self) -> str:
        return "Failing Test Stage"

    def execute(self, run_context: dict[str, Any]) -> dict[str, Any]:
        raise ValueError("Intentional failure for testing")


class _GateStage(BaseStage):
    """A gate stage (is_gate = True)."""

    is_gate: ClassVar[bool] = True

    @property
    def stage_id(self) -> str:
        return "test_gate"

    @property
    def display_name(self) -> str:
        return "Gate Test Stage"

    def execute(self, run_context: dict[str, Any]) -> dict[str, Any]:
        return {"status": "gate_passed"}


# ---------------------------------------------------------------------------
# Test: Stage identity
# ---------------------------------------------------------------------------


class TestStageIdentity:
    """Concrete stages must expose correct identity properties."""

    def test_stage_id(self):
        stage = _PassingStage()
        assert stage.stage_id == "test_passing"

    def test_display_name(self):
        stage = _PassingStage()
        assert stage.display_name == "Passing Test Stage"

    def test_repr(self):
        stage = _PassingStage()
        assert "test_passing" in repr(stage)

    def test_gate_repr(self):
        gate = _GateStage()
        assert "[GATE]" in repr(gate)
        assert gate.is_gate is True


# ---------------------------------------------------------------------------
# Test: Lifecycle (run_stage)
# ---------------------------------------------------------------------------


class TestStageLifecycle:
    """run_stage must enforce the full lifecycle ordering."""

    def test_run_stage_produces_result_with_hashes(self):
        """Successful run_stage should return result with _input_hash and _output_hash."""
        stage = _PassingStage()
        ctx = {"run_id": "test-run-001", "stage_states": {}, "stage_definitions": {}}

        result = stage.run_stage(ctx)

        assert result["status"] == "passed"
        assert "_input_hash" in result
        assert "_output_hash" in result
        assert len(result["_input_hash"]) > 0
        assert len(result["_output_hash"]) > 0

    def test_run_stage_records_to_context(self):
        """run_stage should store results in run_context['stage_results']."""
        stage = _PassingStage()
        ctx = {"run_id": "test-run-002", "stage_states": {}, "stage_definitions": {}}

        stage.run_stage(ctx)

        assert "test_passing" in ctx["stage_results"]
        assert ctx["stage_results"]["test_passing"]["status"] == "passed"

    def test_run_stage_builds_ledger_record(self):
        """run_stage should append a ledger record to pending_ledger_entries."""
        stage = _PassingStage()
        ctx = {"run_id": "test-run-003", "stage_states": {}, "stage_definitions": {}}

        stage.run_stage(ctx)

        entries = ctx.get("pending_ledger_entries", [])
        assert len(entries) == 1
        assert entries[0]["stage_id"] == "test_passing"
        assert entries[0]["run_id"] == "test-run-003"

    def test_run_stage_wraps_exception(self):
        """execute() exception should be wrapped in StageExecutionError."""
        stage = _FailingStage()
        ctx = {"run_id": "test-run-004", "stage_states": {}, "stage_definitions": {}}

        with pytest.raises(StageExecutionError, match="Intentional failure"):
            stage.run_stage(ctx)


# ---------------------------------------------------------------------------
# Test: Prerequisite enforcement
# ---------------------------------------------------------------------------


class TestPrerequisiteEnforcement:
    """validate_prerequisites must block when prerequisites aren't met."""

    def test_no_prerequisites_passes(self):
        """A stage with no prerequisites should pass validation."""
        stage = _PassingStage()
        ctx = {"stage_states": {}, "stage_definitions": {}}
        # Should not raise
        stage.validate_prerequisites(ctx)

    def test_met_prerequisites_passes(self):
        """Prerequisites that are PASSED should allow execution."""
        stage = _PassingStage()
        ctx = {
            "stage_states": {"s0_intake": StageState.PASSED},
            "stage_definitions": {
                "test_passing": {"prerequisites": ["s0_intake"]}
            },
        }
        # Should not raise
        stage.validate_prerequisites(ctx)

    def test_waived_prerequisite_passes(self):
        """WAIVED prerequisites should also satisfy the check."""
        stage = _PassingStage()
        ctx = {
            "stage_states": {"s0_intake": StageState.WAIVED},
            "stage_definitions": {
                "test_passing": {"prerequisites": ["s0_intake"]}
            },
        }
        stage.validate_prerequisites(ctx)

    def test_unmet_prerequisite_raises(self):
        """NOT_STARTED prerequisites must block with StagePrerequisiteError."""
        stage = _PassingStage()
        ctx = {
            "stage_states": {"s0_intake": StageState.NOT_STARTED},
            "stage_definitions": {
                "test_passing": {"prerequisites": ["s0_intake"]}
            },
        }
        with pytest.raises(StagePrerequisiteError, match="s0_intake"):
            stage.validate_prerequisites(ctx)

    def test_failed_prerequisite_raises(self):
        """FAILED prerequisites must block execution."""
        stage = _PassingStage()
        ctx = {
            "stage_states": {"s0_intake": StageState.FAILED},
            "stage_definitions": {
                "test_passing": {"prerequisites": ["s0_intake"]}
            },
        }
        with pytest.raises(StagePrerequisiteError, match="s0_intake"):
            stage.validate_prerequisites(ctx)
