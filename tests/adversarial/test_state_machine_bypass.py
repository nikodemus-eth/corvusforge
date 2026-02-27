"""Adversarial tests — state machine and prerequisite bypass attempts.

These tests verify that:
1. Invalid state transitions are always rejected
2. Prerequisites cannot be bypassed
3. Mandatory gates cannot be skipped
4. Cascade blocking is thorough (no orphaned stages)
5. Terminal states cannot be exited
"""

from __future__ import annotations

import pytest

from corvusforge.core.prerequisite_graph import PrerequisiteGraph, PrerequisiteNotMetError
from corvusforge.core.run_ledger import RunLedger
from corvusforge.core.stage_machine import InvalidTransitionError, StageMachine
from corvusforge.models.stages import DEFAULT_STAGE_DEFINITIONS, StageState


class TestPrerequisiteBypassAttempts:
    """Try to start stages without satisfying prerequisites."""

    @pytest.fixture
    def sm(self, tmp_path) -> tuple[StageMachine, str]:
        ledger = RunLedger(tmp_path / "ledger.db")
        graph = PrerequisiteGraph(DEFAULT_STAGE_DEFINITIONS)
        sm = StageMachine(ledger, graph)
        run_id = "cf-adversarial-sm"
        sm.initialize_run(run_id)
        return sm, run_id

    def test_cannot_skip_to_s5_without_s0_through_s4(self, sm):
        """Attempting to start s5 without completing s0-s4 must fail."""
        machine, run_id = sm
        with pytest.raises(PrerequisiteNotMetError):
            machine.transition(run_id, "s5_implementation", StageState.RUNNING)

    def test_cannot_start_verification_without_gates(self, sm):
        """s6_verification requires BOTH s55 and s575. Passing only one must fail."""
        machine, run_id = sm
        # Walk through s0→s5
        for sid in ["s0_intake", "s1_prerequisites", "s2_environment",
                     "s3_test_contract", "s4_code_plan", "s5_implementation"]:
            machine.transition(run_id, sid, StageState.RUNNING)
            machine.transition(run_id, sid, StageState.PASSED)

        # Pass only s55, not s575
        machine.transition(run_id, "s55_accessibility", StageState.RUNNING)
        machine.transition(run_id, "s55_accessibility", StageState.PASSED)

        # s6 should still be blocked (s575 not passed)
        with pytest.raises(PrerequisiteNotMetError, match="Security"):
            machine.transition(run_id, "s6_verification", StageState.RUNNING)

    def test_cannot_start_release_without_verification(self, sm):
        """s7_release requires s6_verification. Skipping must fail."""
        machine, run_id = sm
        with pytest.raises(PrerequisiteNotMetError):
            machine.transition(run_id, "s7_release", StageState.RUNNING)


class TestInvalidTransitionAttempts:
    """Try to make transitions that violate the VALID_TRANSITIONS table."""

    @pytest.fixture
    def sm(self, tmp_path) -> tuple[StageMachine, str]:
        ledger = RunLedger(tmp_path / "ledger.db")
        graph = PrerequisiteGraph(DEFAULT_STAGE_DEFINITIONS)
        sm = StageMachine(ledger, graph)
        run_id = "cf-adversarial-transitions"
        sm.initialize_run(run_id)
        return sm, run_id

    def test_cannot_go_not_started_to_passed(self, sm):
        """NOT_STARTED → PASSED is not a valid transition."""
        machine, run_id = sm
        with pytest.raises(InvalidTransitionError):
            machine.transition(run_id, "s0_intake", StageState.PASSED)

    def test_cannot_go_not_started_to_failed(self, sm):
        """NOT_STARTED → FAILED is not a valid transition."""
        machine, run_id = sm
        with pytest.raises(InvalidTransitionError):
            machine.transition(run_id, "s0_intake", StageState.FAILED)

    def test_cannot_exit_terminal_passed(self, sm):
        """PASSED is terminal — no transitions out."""
        machine, run_id = sm
        machine.transition(run_id, "s0_intake", StageState.RUNNING)
        machine.transition(run_id, "s0_intake", StageState.PASSED)
        with pytest.raises(InvalidTransitionError):
            machine.transition(run_id, "s0_intake", StageState.RUNNING)

    def test_cannot_exit_terminal_waived(self, sm):
        """WAIVED is terminal — no transitions out."""
        machine, run_id = sm
        # BLOCKED first, then WAIVED
        machine.transition(run_id, "s0_intake", StageState.BLOCKED)
        machine.transition(run_id, "s0_intake", StageState.WAIVED)
        with pytest.raises(InvalidTransitionError):
            machine.transition(run_id, "s0_intake", StageState.RUNNING)

    def test_cannot_go_running_to_not_started(self, sm):
        """RUNNING → NOT_STARTED is not valid (must go through FAILED first)."""
        machine, run_id = sm
        machine.transition(run_id, "s0_intake", StageState.RUNNING)
        with pytest.raises(InvalidTransitionError):
            machine.transition(run_id, "s0_intake", StageState.NOT_STARTED)


class TestCascadeBlockingCompleteness:
    """Verify that cascade blocking is thorough and leaves no orphaned stages."""

    def test_s0_failure_blocks_entire_pipeline(self, tmp_path):
        """If s0 fails, every downstream stage should be BLOCKED."""
        ledger = RunLedger(tmp_path / "ledger.db")
        graph = PrerequisiteGraph(DEFAULT_STAGE_DEFINITIONS)
        sm = StageMachine(ledger, graph)
        run_id = "cf-cascade-test"
        sm.initialize_run(run_id)

        sm.transition(run_id, "s0_intake", StageState.RUNNING)
        sm.transition(run_id, "s0_intake", StageState.FAILED)

        states = sm.get_all_states(run_id)
        for stage_id, state in states.items():
            if stage_id == "s0_intake":
                assert state == StageState.FAILED
            else:
                assert state == StageState.BLOCKED, (
                    f"{stage_id} should be BLOCKED after s0 failure, got {state}"
                )

    def test_s5_failure_blocks_gates_and_downstream(self, tmp_path):
        """If s5 fails, s55, s575, s6, s7 should all be BLOCKED."""
        ledger = RunLedger(tmp_path / "ledger.db")
        graph = PrerequisiteGraph(DEFAULT_STAGE_DEFINITIONS)
        sm = StageMachine(ledger, graph)
        run_id = "cf-cascade-s5"
        sm.initialize_run(run_id)

        for sid in ["s0_intake", "s1_prerequisites", "s2_environment",
                     "s3_test_contract", "s4_code_plan"]:
            sm.transition(run_id, sid, StageState.RUNNING)
            sm.transition(run_id, sid, StageState.PASSED)

        sm.transition(run_id, "s5_implementation", StageState.RUNNING)
        sm.transition(run_id, "s5_implementation", StageState.FAILED)

        states = sm.get_all_states(run_id)
        for blocked_id in ["s55_accessibility", "s575_security",
                            "s6_verification", "s7_release"]:
            assert states[blocked_id] == StageState.BLOCKED, (
                f"{blocked_id} should be BLOCKED after s5 failure"
            )
