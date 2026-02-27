"""Stage state machine models — deterministic transitions (Invariants 4, 5, 6)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class StageState(str, Enum):
    """Strict state model for each pipeline stage."""

    NOT_STARTED = "not_started"
    RUNNING = "running"
    BLOCKED = "blocked"
    FAILED = "failed"
    PASSED = "passed"
    WAIVED = "waived"


# Valid state transitions — enforced structurally by StageMachine.
# Terminal states (PASSED, WAIVED) have no outgoing transitions.
VALID_TRANSITIONS: dict[StageState, set[StageState]] = {
    StageState.NOT_STARTED: {StageState.RUNNING, StageState.BLOCKED},
    StageState.RUNNING: {StageState.PASSED, StageState.FAILED, StageState.BLOCKED},
    StageState.BLOCKED: {StageState.NOT_STARTED, StageState.WAIVED},
    StageState.FAILED: {StageState.NOT_STARTED},  # retry
    StageState.PASSED: set(),  # terminal
    StageState.WAIVED: set(),  # terminal
}


class StageDefinition(BaseModel):
    """Defines a pipeline stage and its prerequisites.

    The prerequisite list encodes the DAG: a stage cannot enter RUNNING
    unless every prerequisite is PASSED or WAIVED.
    """

    model_config = ConfigDict(frozen=True)

    stage_id: str
    display_name: str
    ordinal: float  # 0, 1, 2, ..., 5.5, 5.75, 6, 7
    prerequisites: list[str] = []  # stage_ids that must be PASSED or WAIVED
    is_mandatory_gate: bool = False  # True for accessibility and security gates


class StageTransition(BaseModel):
    """Records a single state transition for audit trail."""

    model_config = ConfigDict(frozen=True)

    stage_id: str
    from_state: StageState
    to_state: StageState
    block_reason: str | None = None  # populated when entering BLOCKED
    upstream_ref: str | None = None  # stage_id that caused the block


# The standard Corvusforge pipeline stages.
DEFAULT_STAGE_DEFINITIONS: list[StageDefinition] = [
    StageDefinition(
        stage_id="s0_intake",
        display_name="Intake",
        ordinal=0.0,
        prerequisites=[],
    ),
    StageDefinition(
        stage_id="s1_prerequisites",
        display_name="Prerequisites Synthesis",
        ordinal=1.0,
        prerequisites=["s0_intake"],
    ),
    StageDefinition(
        stage_id="s2_environment",
        display_name="Environment Readiness",
        ordinal=2.0,
        prerequisites=["s1_prerequisites"],
    ),
    StageDefinition(
        stage_id="s3_test_contract",
        display_name="Test Contracting",
        ordinal=3.0,
        prerequisites=["s2_environment"],
    ),
    StageDefinition(
        stage_id="s4_code_plan",
        display_name="Code Plan",
        ordinal=4.0,
        prerequisites=["s3_test_contract"],
    ),
    StageDefinition(
        stage_id="s5_implementation",
        display_name="Implementation",
        ordinal=5.0,
        prerequisites=["s4_code_plan"],
    ),
    StageDefinition(
        stage_id="s55_accessibility",
        display_name="Accessibility Gate",
        ordinal=5.5,
        prerequisites=["s5_implementation"],
        is_mandatory_gate=True,
    ),
    StageDefinition(
        stage_id="s575_security",
        display_name="Security & Red Team Gate",
        ordinal=5.75,
        prerequisites=["s5_implementation"],
        is_mandatory_gate=True,
    ),
    StageDefinition(
        stage_id="s6_verification",
        display_name="Verification",
        ordinal=6.0,
        prerequisites=["s55_accessibility", "s575_security"],
    ),
    StageDefinition(
        stage_id="s7_release",
        display_name="Release & Attestation",
        ordinal=7.0,
        prerequisites=["s6_verification"],
    ),
]
