"""Tests for the StageMachine — state transitions, prerequisite enforcement, cascades."""

from __future__ import annotations

import pytest

from corvusforge.core.prerequisite_graph import PrerequisiteNotMetError
from corvusforge.core.stage_machine import InvalidTransitionError, StageMachine
from corvusforge.models.stages import StageState


class TestStageMachine:
    def test_initialize_run(self, stage_machine: StageMachine, run_id: str):
        states = stage_machine.initialize_run(run_id)
        assert all(s == StageState.NOT_STARTED for s in states.values())
        assert len(states) == 10

    def test_transition_to_running(self, stage_machine: StageMachine, run_id: str):
        stage_machine.initialize_run(run_id)
        entry = stage_machine.transition(run_id, "s0_intake", StageState.RUNNING)
        assert entry.state_transition == "not_started->running"
        assert stage_machine.get_current_state(run_id, "s0_intake") == StageState.RUNNING

    def test_transition_to_passed(self, stage_machine: StageMachine, run_id: str):
        stage_machine.initialize_run(run_id)
        stage_machine.transition(run_id, "s0_intake", StageState.RUNNING)
        entry = stage_machine.transition(run_id, "s0_intake", StageState.PASSED)
        assert entry.state_transition == "running->passed"

    def test_invalid_transition_rejected(self, stage_machine: StageMachine, run_id: str):
        stage_machine.initialize_run(run_id)
        with pytest.raises(InvalidTransitionError):
            # Cannot go directly from NOT_STARTED to PASSED
            stage_machine.transition(run_id, "s0_intake", StageState.PASSED)

    def test_prerequisite_enforcement(self, stage_machine: StageMachine, run_id: str):
        stage_machine.initialize_run(run_id)
        with pytest.raises(PrerequisiteNotMetError):
            # s1 requires s0 to be PASSED first
            stage_machine.transition(run_id, "s1_prerequisites", StageState.RUNNING)

    def test_prerequisite_met_after_pass(self, stage_machine: StageMachine, run_id: str):
        stage_machine.initialize_run(run_id)
        stage_machine.transition(run_id, "s0_intake", StageState.RUNNING)
        stage_machine.transition(run_id, "s0_intake", StageState.PASSED)
        # Now s1 should be startable
        entry = stage_machine.transition(run_id, "s1_prerequisites", StageState.RUNNING)
        assert entry.state_transition == "not_started->running"

    def test_cascade_block_on_failure(self, stage_machine: StageMachine, run_id: str):
        stage_machine.initialize_run(run_id)
        stage_machine.transition(run_id, "s0_intake", StageState.RUNNING)
        stage_machine.transition(run_id, "s0_intake", StageState.FAILED)
        # Dependents should be blocked
        assert stage_machine.get_current_state(run_id, "s1_prerequisites") == StageState.BLOCKED

    def test_can_start(self, stage_machine: StageMachine, run_id: str):
        stage_machine.initialize_run(run_id)
        can, reasons = stage_machine.can_start(run_id, "s0_intake")
        assert can is True
        assert reasons == []

        can, reasons = stage_machine.can_start(run_id, "s1_prerequisites")
        assert can is False
        assert len(reasons) > 0

    def test_get_available_transitions(self, stage_machine: StageMachine, run_id: str):
        stage_machine.initialize_run(run_id)
        available = stage_machine.get_available_transitions(run_id, "s0_intake")
        assert StageState.RUNNING in available
        assert StageState.BLOCKED in available
        assert StageState.PASSED not in available

    def test_retry_after_failure(self, stage_machine: StageMachine, run_id: str):
        stage_machine.initialize_run(run_id)
        stage_machine.transition(run_id, "s0_intake", StageState.RUNNING)
        stage_machine.transition(run_id, "s0_intake", StageState.FAILED)
        # Retry: FAILED -> NOT_STARTED
        stage_machine.transition(run_id, "s0_intake", StageState.NOT_STARTED)
        assert stage_machine.get_current_state(run_id, "s0_intake") == StageState.NOT_STARTED

    def test_terminal_states_have_no_transitions(self, stage_machine: StageMachine, run_id: str):
        stage_machine.initialize_run(run_id)
        stage_machine.transition(run_id, "s0_intake", StageState.RUNNING)
        stage_machine.transition(run_id, "s0_intake", StageState.PASSED)
        with pytest.raises(InvalidTransitionError):
            stage_machine.transition(run_id, "s0_intake", StageState.RUNNING)
