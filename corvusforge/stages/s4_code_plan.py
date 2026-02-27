"""Stage 4 — Code Plan.

Produces the implementation plan that Stage 5 will execute.  The plan
captures:
    - File-level change specifications (create / modify / delete).
    - Ordered implementation steps with dependencies between them.
    - Mapping from test contracts (Stage 3) to the code that satisfies them.
    - Risk annotations for complex or high-impact changes.

The plan is content-addressed and stored as an immutable artifact.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, ClassVar

from corvusforge.core.hasher import content_address
from corvusforge.stages.base import BaseStage

logger = logging.getLogger(__name__)


class CodePlanStage(BaseStage):
    """Stage 4: Code Plan — produces the implementation blueprint."""

    is_gate: ClassVar[bool] = False

    @property
    def stage_id(self) -> str:
        return "s4_code_plan"

    @property
    def display_name(self) -> str:
        return "Code Plan"

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def execute(self, run_context: dict[str, Any]) -> dict[str, Any]:
        """Build the implementation plan from contracts and work request.

        Reads from *run_context*:
            ``work_request`` — the original work specification.
            ``stage_results.s3_test_contract`` — test contracts.
            ``stage_results.s1_prerequisites`` — dependency graph.

        Returns the structured code plan.
        """
        run_id: str = run_context.get("run_id", "")
        work_request: dict[str, Any] = run_context.get("work_request", {})

        # Retrieve test contracts from Stage 3
        s3_result = run_context.get("stage_results", {}).get(
            "s3_test_contract", {}
        )
        test_contracts: list[dict[str, Any]] = s3_result.get(
            "test_contracts", []
        )

        # --- Build file change specifications --------------------------
        file_changes: list[dict[str, Any]] = self._plan_file_changes(
            work_request
        )

        # --- Build ordered implementation steps -------------------------
        impl_steps: list[dict[str, Any]] = self._plan_implementation_steps(
            work_request, test_contracts, file_changes
        )

        # --- Build contract-to-code mapping ----------------------------
        contract_mapping: list[dict[str, Any]] = (
            self._map_contracts_to_steps(test_contracts, impl_steps)
        )

        # --- Risk annotations ------------------------------------------
        risk_annotations: list[dict[str, Any]] = self._annotate_risks(
            impl_steps
        )

        # --- Assemble the full plan ------------------------------------
        code_plan: dict[str, Any] = {
            "file_changes": file_changes,
            "implementation_steps": impl_steps,
            "contract_mapping": contract_mapping,
            "risk_annotations": risk_annotations,
        }
        plan_ref = content_address(code_plan)

        timestamp = datetime.now(timezone.utc).isoformat()

        return {
            "run_id": run_id,
            "code_plan": code_plan,
            "total_file_changes": len(file_changes),
            "total_steps": len(impl_steps),
            "total_risks": len(risk_annotations),
            "unmapped_contracts": [
                m["contract_id"]
                for m in contract_mapping
                if not m.get("step_ids")
            ],
            "plan_artifact_ref": plan_ref,
            "planned_at": timestamp,
            "_artifact_refs": [plan_ref],
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _plan_file_changes(
        work_request: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Derive file-level change specs from the work request."""
        explicit = work_request.get("file_changes", [])
        if explicit:
            return [
                {
                    "change_id": fc.get("change_id", f"fc-{uuid.uuid4().hex[:8]}"),
                    "path": fc.get("path", ""),
                    "action": fc.get("action", "modify"),  # create / modify / delete
                    "description": fc.get("description", ""),
                    "estimated_lines": fc.get("estimated_lines", 0),
                }
                for fc in explicit
            ]
        return []

    @staticmethod
    def _plan_implementation_steps(
        work_request: dict[str, Any],
        test_contracts: list[dict[str, Any]],
        file_changes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Create ordered implementation steps.

        Each step is an atomic unit of work that the implementation stage
        can execute, verify, and roll back independently.
        """
        steps: list[dict[str, Any]] = []
        explicit = work_request.get("implementation_steps", [])
        if explicit:
            for idx, raw in enumerate(explicit):
                steps.append({
                    "step_id": raw.get("step_id", f"step-{idx:03d}"),
                    "order": idx,
                    "description": raw.get("description", ""),
                    "file_change_ids": raw.get("file_change_ids", []),
                    "depends_on": raw.get("depends_on", []),
                    "complexity": raw.get("complexity", "low"),
                })
            return steps

        # Auto-generate one step per file change when no explicit steps
        for idx, fc in enumerate(file_changes):
            steps.append({
                "step_id": f"step-{idx:03d}",
                "order": idx,
                "description": f"{fc['action'].capitalize()} {fc['path']}",
                "file_change_ids": [fc["change_id"]],
                "depends_on": [f"step-{idx - 1:03d}"] if idx > 0 else [],
                "complexity": "low",
            })
        return steps

    @staticmethod
    def _map_contracts_to_steps(
        contracts: list[dict[str, Any]],
        steps: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Map each test contract to the implementation step(s) that fulfil it.

        Uses ``target_component`` matching against step descriptions.
        """
        mapping: list[dict[str, Any]] = []
        for contract in contracts:
            target = contract.get("target_component", "").lower()
            matched_steps: list[str] = []
            if target:
                for step in steps:
                    if target in step.get("description", "").lower():
                        matched_steps.append(step["step_id"])
            mapping.append({
                "contract_id": contract["contract_id"],
                "step_ids": matched_steps,
            })
        return mapping

    @staticmethod
    def _annotate_risks(
        steps: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Flag high-complexity or high-dependency steps as risks."""
        risks: list[dict[str, Any]] = []
        for step in steps:
            complexity = step.get("complexity", "low")
            dep_count = len(step.get("depends_on", []))
            if complexity in ("high", "critical") or dep_count >= 3:
                risks.append({
                    "step_id": step["step_id"],
                    "risk_level": "high" if complexity == "critical" else "medium",
                    "reason": (
                        f"Complexity={complexity}, dependency_count={dep_count}"
                    ),
                })
        return risks
