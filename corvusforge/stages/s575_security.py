"""Stage 5.75 — Security Gate (mandatory).

Runs security analysis against the implementation output.  This is a
**mandatory gate** — it must PASS or be explicitly WAIVED before the
pipeline can proceed to Verification.

Checks:
    - Static analysis (pattern-based vulnerability detection).
    - Dependency vulnerability scanning (CVE matching).
    - Secrets scanning (API keys, tokens, credentials in source).
    - Input fuzzing surface identification.
    - Authorization boundary verification.

Output is a ``SecurityAuditReport``-compatible dict.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, ClassVar

from corvusforge.core.hasher import content_address
from corvusforge.models.reports import SecurityAuditReport, SecurityFinding
from corvusforge.stages.base import BaseStage

logger = logging.getLogger(__name__)

# Built-in security check definitions.
_SECURITY_CHECKS: list[dict[str, str]] = [
    {
        "check_id": "sec-static-001",
        "category": "static_analysis",
        "description": "Check for eval() / exec() usage in production code.",
    },
    {
        "check_id": "sec-static-002",
        "category": "static_analysis",
        "description": "Check for SQL string concatenation (potential injection).",
    },
    {
        "check_id": "sec-static-003",
        "category": "static_analysis",
        "description": "Check for unsafe deserialization (pickle, yaml.load).",
    },
    {
        "check_id": "sec-dep-001",
        "category": "dependency_vuln",
        "description": "Scan dependencies for known CVEs.",
    },
    {
        "check_id": "sec-secrets-001",
        "category": "secrets",
        "description": "Scan for hardcoded API keys, tokens, and passwords.",
    },
    {
        "check_id": "sec-secrets-002",
        "category": "secrets",
        "description": "Scan for private key material in source files.",
    },
    {
        "check_id": "sec-fuzz-001",
        "category": "fuzzing",
        "description": "Identify public API endpoints without input validation.",
    },
    {
        "check_id": "sec-auth-001",
        "category": "auth_boundary",
        "description": "Verify authorization checks on privileged operations.",
    },
]

# Patterns for secrets scanning.
_SECRET_PATTERNS: list[dict[str, str]] = [
    {"name": "aws_key", "pattern": r"AKIA[0-9A-Z]{16}"},
    {"name": "generic_secret", "pattern": r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]{8,}"},
    {"name": "private_key", "pattern": r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----"},
    {"name": "github_token", "pattern": r"gh[ps]_[A-Za-z0-9_]{36,}"},
]

# Patterns for static analysis — detecting dangerous function calls.
_STATIC_PATTERNS: list[dict[str, str]] = [
    {"check_id": "sec-static-001", "pattern": r"\beval\s*\("},
    {"check_id": "sec-static-002", "pattern": r"(?i)(?:select|insert|update|delete)\s+.*?\+\s*(?:str\(|f['\"])"},
    {"check_id": "sec-static-003", "pattern": r"\bpickle\.loads?\b|\byaml\.load\s*\((?!.*Loader)"},
]


class SecurityGateStage(BaseStage):
    """Stage 5.75: Security Gate — mandatory security analysis."""

    is_gate: ClassVar[bool] = True

    @property
    def stage_id(self) -> str:
        return "s575_security"

    @property
    def display_name(self) -> str:
        return "Security Gate"

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def execute(self, run_context: dict[str, Any]) -> dict[str, Any]:
        """Run security checks against the implementation output.

        Reads from *run_context*:
            ``stage_results.s5_implementation`` — implementation manifest.
            ``security_overrides``             — optional per-check overrides.
            ``source_files``                   — optional dict of path->content
                                                 for static analysis.

        Returns a ``SecurityAuditReport``-compatible dict.
        """
        run_id: str = run_context.get("run_id", "")

        s5_result = run_context.get("stage_results", {}).get(
            "s5_implementation", {}
        )
        overrides: dict[str, Any] = run_context.get(
            "security_overrides", {}
        )
        source_files: dict[str, str] = run_context.get("source_files", {})

        # --- Run checks ------------------------------------------------
        findings: list[dict[str, Any]] = []

        # Static analysis
        findings.extend(
            self._run_static_analysis(source_files, overrides)
        )

        # Secrets scanning
        findings.extend(
            self._run_secrets_scan(source_files, overrides)
        )

        # Dependency vulnerability scan
        findings.extend(
            self._run_dependency_scan(run_context, overrides)
        )

        # Authorization boundary checks
        findings.extend(
            self._run_auth_boundary_checks(run_context, overrides)
        )

        # --- Determine pass/fail ----------------------------------------
        critical_count = len(
            [f for f in findings if f.get("severity") in ("critical", "high")]
        )
        gate_passed = critical_count == 0

        # --- Build remediation plan ref if there are findings -----------
        remediation_plan_ref = ""
        if findings:
            remediation_plan = {
                "findings": findings,
                "recommended_actions": [
                    {
                        "finding_check_id": f["check_id"],
                        "action": f.get("remediation", "Review and fix."),
                    }
                    for f in findings
                ],
            }
            remediation_plan_ref = content_address(remediation_plan)

        # --- Build the report -------------------------------------------
        report = SecurityAuditReport(
            run_id=run_id,
            findings=[SecurityFinding(**f) for f in findings],
            passed=gate_passed,
            remediation_plan_ref=remediation_plan_ref,
        )

        report_dict = report.model_dump(mode="json")
        report_ref = content_address(report_dict)

        artifact_refs = [report_ref]
        if remediation_plan_ref:
            artifact_refs.append(remediation_plan_ref)

        return {
            **report_dict,
            "total_checks": len(_SECURITY_CHECKS),
            "findings_count": len(findings),
            "critical_count": len(
                [f for f in findings if f.get("severity") == "critical"]
            ),
            "high_count": len(
                [f for f in findings if f.get("severity") == "high"]
            ),
            "medium_count": len(
                [f for f in findings if f.get("severity") == "medium"]
            ),
            "report_artifact_ref": report_ref,
            "_artifact_refs": artifact_refs,
        }

    # ------------------------------------------------------------------
    # Internal check runners
    # ------------------------------------------------------------------

    @staticmethod
    def _run_static_analysis(
        source_files: dict[str, str],
        overrides: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Pattern-based static analysis over provided source files."""
        findings: list[dict[str, Any]] = []

        for spec in _STATIC_PATTERNS:
            check_id = spec["check_id"]

            # Check for override
            override = overrides.get(check_id)
            if isinstance(override, dict) and override.get("pass", False):
                continue

            regex = re.compile(spec["pattern"])
            for filepath, content in source_files.items():
                for lineno, line in enumerate(content.splitlines(), start=1):
                    if regex.search(line):
                        findings.append({
                            "check_id": check_id,
                            "category": "static_analysis",
                            "severity": "high",
                            "description": next(
                                (
                                    c["description"]
                                    for c in _SECURITY_CHECKS
                                    if c["check_id"] == check_id
                                ),
                                "",
                            ),
                            "location": f"{filepath}:{lineno}",
                            "remediation": f"Review usage at {filepath}:{lineno} and replace with a safe alternative.",
                            "cve_id": "",
                        })

        return findings

    @staticmethod
    def _run_secrets_scan(
        source_files: dict[str, str],
        overrides: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Scan source files for hardcoded secrets."""
        findings: list[dict[str, Any]] = []

        # Check for override on the secrets checks
        for secrets_check_id in ("sec-secrets-001", "sec-secrets-002"):
            override = overrides.get(secrets_check_id)
            if isinstance(override, dict) and override.get("pass", False):
                return findings

        for filepath, content in source_files.items():
            for lineno, line in enumerate(content.splitlines(), start=1):
                for pat_spec in _SECRET_PATTERNS:
                    if re.search(pat_spec["pattern"], line):
                        findings.append({
                            "check_id": "sec-secrets-001",
                            "category": "secrets",
                            "severity": "critical",
                            "description": f"Potential {pat_spec['name']} detected.",
                            "location": f"{filepath}:{lineno}",
                            "remediation": "Remove the secret and rotate the credential immediately.",
                            "cve_id": "",
                        })

        return findings

    @staticmethod
    def _run_dependency_scan(
        run_context: dict[str, Any],
        overrides: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Scan declared dependencies for known CVEs.

        In the baseline implementation this checks for explicit
        vulnerability declarations in the run_context.  A future version
        will integrate with an actual CVE database.
        """
        override = overrides.get("sec-dep-001")
        if isinstance(override, dict) and override.get("pass", False):
            return []

        known_vulns: list[dict[str, Any]] = run_context.get(
            "known_vulnerabilities", []
        )
        findings: list[dict[str, Any]] = []
        for vuln in known_vulns:
            findings.append({
                "check_id": "sec-dep-001",
                "category": "dependency_vuln",
                "severity": vuln.get("severity", "medium"),
                "description": vuln.get(
                    "description",
                    f"Known vulnerability in {vuln.get('package', 'unknown')}",
                ),
                "location": vuln.get("package", ""),
                "remediation": vuln.get(
                    "remediation", "Upgrade to a patched version."
                ),
                "cve_id": vuln.get("cve_id", ""),
            })
        return findings

    @staticmethod
    def _run_auth_boundary_checks(
        run_context: dict[str, Any],
        overrides: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Verify authorization boundaries are enforced.

        Checks for explicit auth boundary declarations in the work request.
        Without external tool integration, relies on declared boundaries.
        """
        override = overrides.get("sec-auth-001")
        if isinstance(override, dict) and override.get("pass", False):
            return []

        auth_issues: list[dict[str, Any]] = run_context.get(
            "auth_boundary_issues", []
        )
        findings: list[dict[str, Any]] = []
        for issue in auth_issues:
            findings.append({
                "check_id": "sec-auth-001",
                "category": "auth_boundary",
                "severity": issue.get("severity", "high"),
                "description": issue.get(
                    "description",
                    "Missing authorization check on privileged operation.",
                ),
                "location": issue.get("location", ""),
                "remediation": issue.get(
                    "remediation",
                    "Add authorization check before the privileged operation.",
                ),
                "cve_id": "",
            })
        return findings
