"""Gate report models — outputs of accessibility, security, and verification stages."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field


class AccessibilityFinding(BaseModel):
    """A single accessibility check result."""

    model_config = ConfigDict(frozen=True)

    check_id: str  # e.g. "wcag-2.1-1.4.3" (contrast ratio)
    category: str  # "keyboard", "screen_reader", "contrast", "motion", "error_messages"
    severity: str  # "critical", "major", "minor"
    description: str
    element_ref: str = ""  # CSS selector or component path
    remediation: str = ""


class AccessibilityAuditReport(BaseModel):
    """Output of Stage 5.5 — Accessibility Gate.

    Covers WCAG 2.1 AA alignment, keyboard navigation, screen reader
    semantics, contrast/non-color cues, motion reduction, and error
    message association.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    stage_id: str = "s55_accessibility"
    findings: list[AccessibilityFinding] = []
    wcag_score: float = 0.0  # 0-100 alignment score
    passed: bool = False
    remediation_patch_refs: list[str] = []  # content-addressed patch set refs
    config_profile_ref: str = ""  # accessibility config profile artifact ref
    timestamp_utc: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class SecurityFinding(BaseModel):
    """A single security check result."""

    model_config = ConfigDict(frozen=True)

    check_id: str
    category: str  # "static_analysis", "dependency_vuln", "secrets", "fuzzing", "auth_boundary"
    severity: str  # "critical", "high", "medium", "low", "info"
    description: str
    location: str = ""  # file:line or component path
    remediation: str = ""
    cve_id: str = ""


class SecurityAuditReport(BaseModel):
    """Output of Stage 5.75 — Security & Red Team Gate.

    Covers static analysis, dependency vulnerability scanning, secrets
    scanning, misuse case testing, input fuzzing, and authorization
    boundary checks.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    stage_id: str = "s575_security"
    findings: list[SecurityFinding] = []
    passed: bool = False
    remediation_plan_ref: str = ""  # content-addressed remediation plan
    timestamp_utc: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class TestResult(BaseModel):
    """A single test execution result."""

    model_config = ConfigDict(frozen=True)

    test_id: str
    test_name: str
    category: str  # "unit", "e2e", "edge_case", "negative"
    passed: bool
    duration_ms: float = 0.0
    error_message: str = ""


class VerificationGateEvent(BaseModel):
    """Output of Stage 6 — Verification.

    Covers unit tests, e2e tests, coverage, lint, static checks,
    and SBOM generation.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    stage_id: str = "s6_verification"
    test_results: list[TestResult] = []
    total_tests: int = 0
    passed_tests: int = 0
    coverage_percent: float = 0.0
    lint_passed: bool = False
    static_checks_passed: bool = False
    sbom_ref: str = ""  # content-addressed SBOM artifact ref
    passed: bool = False
    timestamp_utc: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
