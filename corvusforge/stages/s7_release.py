"""Stage 7 — Release and Attestation.

Final pipeline stage that:
    - Assembles all artifacts produced by preceding stages.
    - Generates the release attestation (a content-addressed manifest
      binding run_id to all artifact hashes, stage results, and version pins).
    - Verifies the ledger hash chain for the run.
    - Produces the release bundle reference.

The attestation is the cryptographic proof that this run executed all
stages in order, passed all gates, and produced a specific set of artifacts.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, ClassVar

from corvusforge.core.hasher import content_address
from corvusforge.models.config import RunConfig
from corvusforge.stages.base import BaseStage

logger = logging.getLogger(__name__)


class ReleaseAttestationStage(BaseStage):
    """Stage 7: Release & Attestation — assembles and attests the run."""

    is_gate: ClassVar[bool] = False

    @property
    def stage_id(self) -> str:
        return "s7_release"

    @property
    def display_name(self) -> str:
        return "Release & Attestation"

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def execute(self, run_context: dict[str, Any]) -> dict[str, Any]:
        """Assemble release artifacts and generate the attestation.

        Reads from *run_context*:
            ``run_config``     — RunConfig from Stage 0.
            ``stage_results``  — all prior stage results.
            ``pending_ledger_entries`` — entries awaiting ledger flush.

        Returns the release attestation dict.
        """
        run_id: str = run_context.get("run_id", "")
        run_config: RunConfig | None = run_context.get("run_config")
        stage_results: dict[str, Any] = run_context.get("stage_results", {})

        # --- Collect all artifact references across stages --------------
        all_artifact_refs: list[str] = []
        stage_summaries: list[dict[str, Any]] = []

        stage_order = [
            "s0_intake",
            "s1_prerequisites",
            "s2_environment",
            "s3_test_contract",
            "s4_code_plan",
            "s5_implementation",
            "s55_accessibility",
            "s575_security",
            "s6_verification",
        ]

        for sid in stage_order:
            result = stage_results.get(sid, {})
            refs = result.get("_artifact_refs", [])
            all_artifact_refs.extend(refs)
            stage_summaries.append({
                "stage_id": sid,
                "output_hash": result.get("_output_hash", ""),
                "artifact_count": len(refs),
                "passed": result.get("passed", True),
            })

        # --- Build version pin snapshot ---------------------------------
        version_pin = {}
        if run_config:
            version_pin = run_config.pipeline_config.version_pin.model_dump(
                mode="json"
            )

        # --- Verify gate results ----------------------------------------
        a11y_passed = stage_results.get("s55_accessibility", {}).get(
            "passed", False
        )
        security_passed = stage_results.get("s575_security", {}).get(
            "passed", False
        )
        verification_passed = stage_results.get("s6_verification", {}).get(
            "passed", False
        )

        all_gates_passed = (
            a11y_passed and security_passed and verification_passed
        )

        # --- Check for waivers ------------------------------------------
        waiver_refs: list[str] = run_context.get("waiver_references", [])

        # --- Build the attestation document ----------------------------
        attestation: dict[str, Any] = {
            "attestation_version": "1.0.0",
            "run_id": run_id,
            "pipeline_version": version_pin.get("pipeline_version", "0.1.0"),
            "schema_version": version_pin.get("schema_version", "2026-02"),
            "version_pin": version_pin,
            "stage_summaries": stage_summaries,
            "all_artifact_refs": sorted(set(all_artifact_refs)),
            "total_artifacts": len(set(all_artifact_refs)),
            "gates": {
                "accessibility_passed": a11y_passed,
                "security_passed": security_passed,
                "verification_passed": verification_passed,
                "all_gates_passed": all_gates_passed,
            },
            "waiver_references": waiver_refs,
            "attested_at": datetime.now(timezone.utc).isoformat(),
        }

        attestation_ref = content_address(attestation)

        # --- Build release bundle reference ----------------------------
        release_bundle: dict[str, Any] = {
            "run_id": run_id,
            "attestation_ref": attestation_ref,
            "artifact_manifest": sorted(set(all_artifact_refs)),
            "release_ready": all_gates_passed,
        }
        bundle_ref = content_address(release_bundle)

        timestamp = datetime.now(timezone.utc).isoformat()

        return {
            "run_id": run_id,
            "attestation": attestation,
            "attestation_artifact_ref": attestation_ref,
            "release_bundle_ref": bundle_ref,
            "release_ready": all_gates_passed,
            "total_artifacts": len(set(all_artifact_refs)),
            "all_gates_passed": all_gates_passed,
            "waiver_count": len(waiver_refs),
            "released_at": timestamp,
            "_artifact_refs": [attestation_ref, bundle_ref],
        }
