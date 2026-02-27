"""Stage 3 — Test Contracting.

Defines the test contracts that the implementation must satisfy **before**
any code is written.  This is the "tests first" gate — the contracts
become binding obligations for Stage 5 (Implementation) and Stage 6
(Verification).

Outputs:
    test_contracts — list of test contract specifications, each with:
        contract_id, category (unit/e2e/edge_case/negative),
        description, acceptance_criteria, priority.
    contract_artifact_ref — content-addressed reference to the contract set.
    total_contracts / by_category — summary counts.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, ClassVar

from corvusforge.core.hasher import content_address
from corvusforge.stages.base import BaseStage

logger = logging.getLogger(__name__)


class TestContractingStage(BaseStage):
    """Stage 3: Test Contracting — defines test obligations before code."""

    is_gate: ClassVar[bool] = False

    @property
    def stage_id(self) -> str:
        return "s3_test_contract"

    @property
    def display_name(self) -> str:
        return "Test Contracting"

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def execute(self, run_context: dict[str, Any]) -> dict[str, Any]:
        """Build test contracts from the work request and dependency graph.

        Reads from *run_context*:
            ``work_request`` — description of requested work.
            ``stage_results.s1_prerequisites`` — dependency information.

        Returns the full set of test contracts.
        """
        run_id: str = run_context.get("run_id", "")
        work_request: dict[str, Any] = run_context.get("work_request", {})

        # --- Generate contracts from explicit specifications -----------
        explicit_contracts: list[dict[str, Any]] = work_request.get(
            "test_contracts", []
        )
        contracts: list[dict[str, Any]] = [
            self._normalise_contract(c) for c in explicit_contracts
        ]

        # --- Synthesise additional contracts from the work request ------
        synthesised = self._synthesise_contracts(work_request)
        contracts.extend(synthesised)

        # --- De-duplicate by contract_id --------------------------------
        seen_ids: set[str] = set()
        unique_contracts: list[dict[str, Any]] = []
        for c in contracts:
            if c["contract_id"] not in seen_ids:
                seen_ids.add(c["contract_id"])
                unique_contracts.append(c)
        contracts = unique_contracts

        # --- Category summary -------------------------------------------
        by_category: dict[str, int] = {}
        for c in contracts:
            cat = c.get("category", "unit")
            by_category[cat] = by_category.get(cat, 0) + 1

        # --- Content-address the contract set ---------------------------
        contract_set: dict[str, Any] = {
            "run_id": run_id,
            "contracts": contracts,
        }
        contract_ref = content_address(contract_set)

        timestamp = datetime.now(timezone.utc).isoformat()

        return {
            "run_id": run_id,
            "test_contracts": contracts,
            "total_contracts": len(contracts),
            "by_category": by_category,
            "contract_artifact_ref": contract_ref,
            "contracted_at": timestamp,
            "_artifact_refs": [contract_ref],
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_contract(raw: dict[str, Any]) -> dict[str, Any]:
        """Ensure a contract dict has all required fields."""
        return {
            "contract_id": raw.get("contract_id", f"tc-{uuid.uuid4().hex[:8]}"),
            "category": raw.get("category", "unit"),
            "description": raw.get("description", ""),
            "acceptance_criteria": raw.get("acceptance_criteria", []),
            "priority": raw.get("priority", "normal"),
            "target_component": raw.get("target_component", ""),
        }

    @staticmethod
    def _synthesise_contracts(
        work_request: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Generate baseline test contracts from the work request.

        When the work request declares components or features, this method
        generates a default set of contracts (happy path, edge case,
        negative path) for each one.
        """
        contracts: list[dict[str, Any]] = []
        components: list[str] = work_request.get("components", [])
        features: list[str] = work_request.get("features", [])
        targets = components + features

        for target in targets:
            safe_name = target.replace(" ", "_").lower()

            # Happy-path unit test
            contracts.append({
                "contract_id": f"tc-{safe_name}-unit",
                "category": "unit",
                "description": f"Unit test for {target} — happy path.",
                "acceptance_criteria": [
                    f"{target} returns expected output for valid input."
                ],
                "priority": "normal",
                "target_component": target,
            })

            # Edge-case test
            contracts.append({
                "contract_id": f"tc-{safe_name}-edge",
                "category": "edge_case",
                "description": f"Edge-case test for {target} — boundary conditions.",
                "acceptance_criteria": [
                    f"{target} handles boundary and empty inputs gracefully."
                ],
                "priority": "normal",
                "target_component": target,
            })

            # Negative test
            contracts.append({
                "contract_id": f"tc-{safe_name}-negative",
                "category": "negative",
                "description": f"Negative test for {target} — invalid inputs.",
                "acceptance_criteria": [
                    f"{target} raises appropriate errors for invalid input."
                ],
                "priority": "normal",
                "target_component": target,
            })

        return contracts
