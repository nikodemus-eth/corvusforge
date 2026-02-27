"""Deterministic stage state machine (Invariants 4, 5, 6, 7).

Enforces:
- Valid state transitions only (VALID_TRANSITIONS table)
- Prerequisites checked before RUNNING
- Cascade blocking on failure
- Cascade unblocking on retry success
- Every transition recorded in the Run Ledger
"""

from __future__ import annotations

from corvusforge.core.prerequisite_graph import PrerequisiteGraph, PrerequisiteNotMetError
from corvusforge.core.run_ledger import RunLedger
from corvusforge.models.ledger import LedgerEntry
from corvusforge.models.stages import (
    VALID_TRANSITIONS,
    StageState,
)


class InvalidTransitionError(RuntimeError):
    """Raised when a requested state transition is not valid."""


class StageMachine:
    """Enforces the stage state machine with prerequisite checking.

    Parameters
    ----------
    ledger:
        The Run Ledger to record transitions into.
    graph:
        The prerequisite graph for dependency checking.
    """

    def __init__(self, ledger: RunLedger, graph: PrerequisiteGraph) -> None:
        self._ledger = ledger
        self._graph = graph
        # In-memory state cache: run_id -> {stage_id -> StageState}
        self._states: dict[str, dict[str, StageState]] = {}

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def initialize_run(self, run_id: str) -> dict[str, StageState]:
        """Initialize all stages to NOT_STARTED for a new run."""
        states = {
            sid: StageState.NOT_STARTED for sid in self._graph.stage_ids
        }
        self._states[run_id] = states
        return dict(states)

    def get_current_state(self, run_id: str, stage_id: str) -> StageState:
        """Return the current state of a stage in a run."""
        if run_id not in self._states:
            self._rebuild_state(run_id)
        return self._states[run_id].get(stage_id, StageState.NOT_STARTED)

    def get_all_states(self, run_id: str) -> dict[str, StageState]:
        """Return a snapshot of all stage states for a run."""
        if run_id not in self._states:
            self._rebuild_state(run_id)
        return dict(self._states[run_id])

    def _rebuild_state(self, run_id: str) -> None:
        """Rebuild in-memory state from the ledger (for resume)."""
        states = {sid: StageState.NOT_STARTED for sid in self._graph.stage_ids}
        entries = self._ledger.get_run_entries(run_id)
        for entry in entries:
            if "->" in entry.state_transition:
                _, to_state = entry.state_transition.split("->", 1)
                try:
                    states[entry.stage_id] = StageState(to_state)
                except ValueError:
                    pass
        self._states[run_id] = states

    # ------------------------------------------------------------------
    # Transition logic
    # ------------------------------------------------------------------

    def transition(
        self,
        run_id: str,
        stage_id: str,
        target_state: StageState,
        *,
        input_hash: str = "",
        output_hash: str = "",
        artifact_references: list[str] | None = None,
        waiver_references: list[str] | None = None,
        trust_context: dict[str, str] | None = None,
    ) -> LedgerEntry:
        """Transition a stage to a new state, recording in the ledger.

        Validates:
        1. The transition is allowed by VALID_TRANSITIONS.
        2. If target is RUNNING, prerequisites are met.
        3. If transition is to FAILED, cascade-block dependents.

        Returns the sealed LedgerEntry.
        """
        if run_id not in self._states:
            self._rebuild_state(run_id)

        current = self._states[run_id].get(stage_id, StageState.NOT_STARTED)

        # Validate transition is allowed
        allowed = VALID_TRANSITIONS.get(current, set())
        if target_state not in allowed:
            raise InvalidTransitionError(
                f"Cannot transition {stage_id} from {current.value} to {target_state.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )

        # Check prerequisites before entering RUNNING
        if target_state == StageState.RUNNING:
            if not self._graph.are_prerequisites_met(stage_id, self._states[run_id]):
                reasons = self._graph.get_blocking_reasons(
                    stage_id, self._states[run_id]
                )
                raise PrerequisiteNotMetError(
                    f"Cannot start {stage_id}: prerequisites not met. "
                    f"Blocked by: {'; '.join(reasons)}"
                )

        # Record the transition
        transition_str = f"{current.value}->{target_state.value}"
        entry = LedgerEntry(
            run_id=run_id,
            stage_id=stage_id,
            state_transition=transition_str,
            input_hash=input_hash,
            output_hash=output_hash,
            artifact_references=artifact_references or [],
            waiver_references=waiver_references or [],
            trust_context=trust_context or {},
        )
        sealed = self._ledger.append(entry)

        # Update in-memory state
        self._states[run_id][stage_id] = target_state

        # Cascade effects
        if target_state == StageState.FAILED:
            blocked = self._graph.cascade_block(stage_id, self._states[run_id])
            # Record cascade blocks in the ledger
            for blocked_id in blocked:
                block_entry = LedgerEntry(
                    run_id=run_id,
                    stage_id=blocked_id,
                    state_transition=f"{StageState.NOT_STARTED.value}->{StageState.BLOCKED.value}",
                    input_hash="",
                    output_hash="",
                )
                self._ledger.append(block_entry)

        elif target_state == StageState.PASSED:
            unblocked = self._graph.cascade_unblock(stage_id, self._states[run_id])
            # Record cascade unblocks in the ledger
            for unblocked_id in unblocked:
                unblock_entry = LedgerEntry(
                    run_id=run_id,
                    stage_id=unblocked_id,
                    state_transition=f"{StageState.BLOCKED.value}->{StageState.NOT_STARTED.value}",
                    input_hash="",
                    output_hash="",
                )
                self._ledger.append(unblock_entry)

        return sealed

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    def can_start(self, run_id: str, stage_id: str) -> tuple[bool, list[str]]:
        """Check if a stage can transition to RUNNING.

        Returns (can_start, blocking_reasons).
        """
        if run_id not in self._states:
            self._rebuild_state(run_id)

        current = self._states[run_id].get(stage_id, StageState.NOT_STARTED)
        if current != StageState.NOT_STARTED:
            return False, [f"Stage is currently {current.value}, not not_started"]

        if not self._graph.are_prerequisites_met(stage_id, self._states[run_id]):
            reasons = self._graph.get_blocking_reasons(
                stage_id, self._states[run_id]
            )
            return False, reasons

        return True, []

    def get_available_transitions(
        self, run_id: str, stage_id: str
    ) -> set[StageState]:
        """Return the set of valid target states for a stage."""
        current = self.get_current_state(run_id, stage_id)
        return VALID_TRANSITIONS.get(current, set())
