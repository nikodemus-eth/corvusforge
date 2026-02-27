"""Corvusforge pipeline stages — registry mapping stage_id to stage class.

Usage::

    from corvusforge.stages import STAGE_REGISTRY, get_stage

    stage_cls = STAGE_REGISTRY["s0_intake"]
    stage = stage_cls()
    result = stage.run_stage(run_context)

    # Or use the convenience helper:
    stage = get_stage("s55_accessibility")
"""

from __future__ import annotations

from corvusforge.stages.base import BaseStage, StageExecutionError, StagePrerequisiteError
from corvusforge.stages.s0_intake import IntakeStage
from corvusforge.stages.s1_prerequisites import PrerequisitesSynthesisStage
from corvusforge.stages.s2_environment import EnvironmentReadinessStage
from corvusforge.stages.s3_test_contract import TestContractingStage
from corvusforge.stages.s4_code_plan import CodePlanStage
from corvusforge.stages.s5_implementation import ImplementationStage
from corvusforge.stages.s6_verification import VerificationStage
from corvusforge.stages.s7_release import ReleaseAttestationStage
from corvusforge.stages.s55_accessibility import AccessibilityGateStage
from corvusforge.stages.s575_security import SecurityGateStage

# ---------------------------------------------------------------------------
# Stage registry: stage_id -> stage class
# ---------------------------------------------------------------------------

STAGE_REGISTRY: dict[str, type[BaseStage]] = {
    "s0_intake": IntakeStage,
    "s1_prerequisites": PrerequisitesSynthesisStage,
    "s2_environment": EnvironmentReadinessStage,
    "s3_test_contract": TestContractingStage,
    "s4_code_plan": CodePlanStage,
    "s5_implementation": ImplementationStage,
    "s55_accessibility": AccessibilityGateStage,
    "s575_security": SecurityGateStage,
    "s6_verification": VerificationStage,
    "s7_release": ReleaseAttestationStage,
}

# Ordered list matching the default pipeline execution order.
STAGE_ORDER: list[str] = [
    "s0_intake",
    "s1_prerequisites",
    "s2_environment",
    "s3_test_contract",
    "s4_code_plan",
    "s5_implementation",
    "s55_accessibility",
    "s575_security",
    "s6_verification",
    "s7_release",
]

# Gate stages — mandatory checks that must PASS or be WAIVED.
GATE_STAGE_IDS: frozenset[str] = frozenset(
    sid for sid, cls in STAGE_REGISTRY.items() if cls.is_gate
)


def get_stage(stage_id: str) -> BaseStage:
    """Instantiate and return a stage by its ``stage_id``.

    Raises ``KeyError`` if the stage_id is not registered.
    """
    try:
        cls = STAGE_REGISTRY[stage_id]
    except KeyError:
        raise KeyError(
            f"Unknown stage_id {stage_id!r}. "
            f"Registered stages: {sorted(STAGE_REGISTRY.keys())}"
        ) from None
    return cls()


__all__ = [
    # Base
    "BaseStage",
    "StageExecutionError",
    "StagePrerequisiteError",
    # Registry
    "STAGE_REGISTRY",
    "STAGE_ORDER",
    "GATE_STAGE_IDS",
    "get_stage",
    # Concrete stages
    "IntakeStage",
    "PrerequisitesSynthesisStage",
    "EnvironmentReadinessStage",
    "TestContractingStage",
    "CodePlanStage",
    "ImplementationStage",
    "AccessibilityGateStage",
    "SecurityGateStage",
    "VerificationStage",
    "ReleaseAttestationStage",
]
