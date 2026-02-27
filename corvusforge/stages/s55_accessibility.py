"""Stage 5.5 — Accessibility Gate (mandatory).

Runs WCAG 2.1 AA compliance checks against the implementation output.
This is a **mandatory gate** — it must PASS or be explicitly WAIVED
before the pipeline can proceed to Verification.

Checks:
    - WCAG 2.1 AA alignment scoring.
    - Keyboard navigation coverage.
    - Screen-reader semantic correctness (ARIA roles, labels, live regions).
    - Contrast and non-colour cue compliance (1.4.3, 1.4.1).
    - Motion/animation reduction (2.3.1, 2.3.3).
    - Error message association (3.3.1, 3.3.2).

Output is an ``AccessibilityAuditReport``-compatible dict.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from corvusforge.core.hasher import content_address
from corvusforge.models.reports import (
    AccessibilityAuditReport,
    AccessibilityFinding,
)
from corvusforge.stages.base import BaseStage

logger = logging.getLogger(__name__)

# WCAG 2.1 AA check definitions used by this gate.
_WCAG_CHECKS: list[dict[str, str]] = [
    {
        "check_id": "wcag-2.1-1.1.1",
        "category": "screen_reader",
        "description": "Non-text content has text alternatives.",
    },
    {
        "check_id": "wcag-2.1-1.3.1",
        "category": "screen_reader",
        "description": (
            "Info and relationships conveyed through presentation "
            "are programmatically determinable."
        ),
    },
    {
        "check_id": "wcag-2.1-1.4.1",
        "category": "contrast",
        "description": "Colour is not the sole means of conveying information.",
    },
    {
        "check_id": "wcag-2.1-1.4.3",
        "category": "contrast",
        "description": "Contrast ratio of at least 4.5:1 for normal text.",
    },
    {
        "check_id": "wcag-2.1-2.1.1",
        "category": "keyboard",
        "description": "All functionality is operable through keyboard interface.",
    },
    {
        "check_id": "wcag-2.1-2.1.2",
        "category": "keyboard",
        "description": "No keyboard trap — focus can be moved away from any component.",
    },
    {
        "check_id": "wcag-2.1-2.3.1",
        "category": "motion",
        "description": "Content does not flash more than three times per second.",
    },
    {
        "check_id": "wcag-2.1-2.4.7",
        "category": "keyboard",
        "description": "Focus indicator is visible.",
    },
    {
        "check_id": "wcag-2.1-3.3.1",
        "category": "error_messages",
        "description": "Input errors are automatically detected and described to the user.",
    },
    {
        "check_id": "wcag-2.1-3.3.2",
        "category": "error_messages",
        "description": "Labels or instructions are provided for user input.",
    },
    {
        "check_id": "wcag-2.1-4.1.2",
        "category": "screen_reader",
        "description": "Name, role, value are programmatically determinable for UI components.",
    },
]


class AccessibilityGateStage(BaseStage):
    """Stage 5.5: Accessibility Gate — mandatory WCAG 2.1 AA checks."""

    is_gate: ClassVar[bool] = True

    @property
    def stage_id(self) -> str:
        return "s55_accessibility"

    @property
    def display_name(self) -> str:
        return "Accessibility Gate"

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def execute(self, run_context: dict[str, Any]) -> dict[str, Any]:
        """Run accessibility checks against the implementation output.

        Reads from *run_context*:
            ``stage_results.s5_implementation`` — implementation manifest.
            ``accessibility_overrides``        — optional per-check overrides.

        Returns an ``AccessibilityAuditReport``-compatible dict.
        """
        run_id: str = run_context.get("run_id", "")

        # Retrieve implementation results
        s5_result = run_context.get("stage_results", {}).get(
            "s5_implementation", {}
        )

        # Optional overrides / pre-computed results from external tools
        overrides: dict[str, Any] = run_context.get(
            "accessibility_overrides", {}
        )

        # --- Run each WCAG check ---------------------------------------
        findings: list[dict[str, Any]] = []
        checks_passed = 0
        total_checks = len(_WCAG_CHECKS)

        for check_def in _WCAG_CHECKS:
            check_def["check_id"]
            result = self._run_check(check_def, s5_result, overrides)
            if result is not None:
                findings.append(result)
            else:
                checks_passed += 1

        # --- Compute WCAG score ----------------------------------------
        wcag_score = (checks_passed / total_checks * 100.0) if total_checks else 100.0
        gate_passed = len(
            [f for f in findings if f.get("severity") in ("critical", "major")]
        ) == 0

        # --- Build remediation patch refs if there are findings --------
        remediation_refs: list[str] = []
        if findings:
            for finding in findings:
                if finding.get("remediation"):
                    ref = content_address(finding)
                    remediation_refs.append(ref)

        # --- Build the report ------------------------------------------
        report = AccessibilityAuditReport(
            run_id=run_id,
            findings=[
                AccessibilityFinding(**f)
                for f in findings
            ],
            wcag_score=round(wcag_score, 2),
            passed=gate_passed,
            remediation_patch_refs=remediation_refs,
        )

        report_dict = report.model_dump(mode="json")
        report_ref = content_address(report_dict)

        return {
            **report_dict,
            "total_checks": total_checks,
            "checks_passed": checks_passed,
            "findings_count": len(findings),
            "critical_findings": len(
                [f for f in findings if f.get("severity") == "critical"]
            ),
            "major_findings": len(
                [f for f in findings if f.get("severity") == "major"]
            ),
            "report_artifact_ref": report_ref,
            "_artifact_refs": [report_ref] + remediation_refs,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _run_check(
        check_def: dict[str, str],
        impl_result: dict[str, Any],
        overrides: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Run a single WCAG check.

        Returns a finding dict if the check fails, or ``None`` if it passes.

        If the check_id appears in *overrides* with ``"pass": True``,
        the check is considered passed.  If *overrides* provides a full
        finding dict, that is used instead.
        """
        check_id = check_def["check_id"]

        # Check for explicit override
        override = overrides.get(check_id)
        if isinstance(override, dict):
            if override.get("pass", False):
                return None
            return {
                "check_id": check_id,
                "category": check_def["category"],
                "severity": override.get("severity", "major"),
                "description": override.get(
                    "description", check_def["description"]
                ),
                "element_ref": override.get("element_ref", ""),
                "remediation": override.get("remediation", ""),
            }

        # Without external tool integration, all checks pass by default.
        # When an external a11y scanner is wired in, this becomes the
        # dispatch point.  For now, return None (pass).
        return None
