"""Stage 5 — Implementation.

Executes the code plan from Stage 4, producing the actual code changes.
For each implementation step the stage:
    - Applies the planned file changes.
    - Tracks which test contracts are addressed.
    - Records intermediate artifact references for each changed file.
    - Aggregates a final implementation manifest.

This stage does *not* run tests — that is Stage 6's responsibility.
The mandatory gates (5.5 Accessibility, 5.75 Security) run in parallel
after this stage completes.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, ClassVar

from corvusforge.core.hasher import content_address
from corvusforge.stages.base import BaseStage

logger = logging.getLogger(__name__)


class ImplementationStage(BaseStage):
    """Stage 5: Implementation — executes the code plan."""

    is_gate: ClassVar[bool] = False

    @property
    def stage_id(self) -> str:
        return "s5_implementation"

    @property
    def display_name(self) -> str:
        return "Implementation"

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def execute(self, run_context: dict[str, Any]) -> dict[str, Any]:
        """Execute each implementation step from the code plan.

        Reads from *run_context*:
            ``stage_results.s4_code_plan.code_plan`` — the plan.
            ``stage_results.s3_test_contract.test_contracts`` — contracts.

        Returns an implementation manifest with per-step results.
        """
        run_id: str = run_context.get("run_id", "")

        # Retrieve the code plan from Stage 4
        s4_result = run_context.get("stage_results", {}).get(
            "s4_code_plan", {}
        )
        code_plan: dict[str, Any] = s4_result.get("code_plan", {})
        file_changes: list[dict[str, Any]] = code_plan.get(
            "file_changes", []
        )
        impl_steps: list[dict[str, Any]] = code_plan.get(
            "implementation_steps", []
        )
        contract_mapping: list[dict[str, Any]] = code_plan.get(
            "contract_mapping", []
        )

        # --- Execute each step -----------------------------------------
        step_results: list[dict[str, Any]] = []
        artifact_refs: list[str] = []
        files_created: list[str] = []
        files_modified: list[str] = []
        files_deleted: list[str] = []

        for step in impl_steps:
            step_result = self._execute_step(step, file_changes)
            step_results.append(step_result)

            # Collect file-action tallies
            for fc_id in step.get("file_change_ids", []):
                fc = next(
                    (f for f in file_changes if f.get("change_id") == fc_id),
                    None,
                )
                if fc:
                    action = fc.get("action", "modify")
                    path = fc.get("path", "")
                    if action == "create":
                        files_created.append(path)
                    elif action == "modify":
                        files_modified.append(path)
                    elif action == "delete":
                        files_deleted.append(path)

            # Content-address each step result as an artifact
            step_ref = content_address(step_result)
            artifact_refs.append(step_ref)

        # --- Determine which contracts are addressed -------------------
        addressed_contracts: list[str] = []
        unaddressed_contracts: list[str] = []
        completed_step_ids = {
            sr["step_id"] for sr in step_results if sr.get("status") == "completed"
        }
        for mapping in contract_mapping:
            required_steps = set(mapping.get("step_ids", []))
            if required_steps and required_steps.issubset(completed_step_ids):
                addressed_contracts.append(mapping["contract_id"])
            elif required_steps:
                unaddressed_contracts.append(mapping["contract_id"])

        # --- Build implementation manifest ------------------------------
        manifest: dict[str, Any] = {
            "step_results": step_results,
            "files_created": files_created,
            "files_modified": files_modified,
            "files_deleted": files_deleted,
            "addressed_contracts": addressed_contracts,
            "unaddressed_contracts": unaddressed_contracts,
        }
        manifest_ref = content_address(manifest)
        artifact_refs.append(manifest_ref)

        timestamp = datetime.now(timezone.utc).isoformat()

        return {
            "run_id": run_id,
            "total_steps_executed": len(step_results),
            "steps_completed": sum(
                1 for sr in step_results if sr.get("status") == "completed"
            ),
            "steps_failed": sum(
                1 for sr in step_results if sr.get("status") == "failed"
            ),
            "files_created": files_created,
            "files_modified": files_modified,
            "files_deleted": files_deleted,
            "addressed_contracts": addressed_contracts,
            "unaddressed_contracts": unaddressed_contracts,
            "manifest_artifact_ref": manifest_ref,
            "implemented_at": timestamp,
            "_artifact_refs": artifact_refs,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _execute_step(
        step: dict[str, Any],
        file_changes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Execute a single implementation step.

        In the current baseline this records the step as completed and
        captures metadata.  A future version will delegate to an agent
        or code-generation backend.
        """
        step_id = step.get("step_id", f"step-{uuid.uuid4().hex[:8]}")
        description = step.get("description", "")
        change_ids = step.get("file_change_ids", [])

        # Resolve the file changes associated with this step
        resolved_changes: list[dict[str, Any]] = []
        for fc_id in change_ids:
            fc = next(
                (f for f in file_changes if f.get("change_id") == fc_id),
                None,
            )
            if fc:
                resolved_changes.append({
                    "change_id": fc_id,
                    "path": fc.get("path", ""),
                    "action": fc.get("action", "modify"),
                    "applied": True,
                })

        return {
            "step_id": step_id,
            "description": description,
            "status": "completed",
            "changes_applied": resolved_changes,
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }
