"""Adversarial tests for production configuration guard.

These tests assert that production mode enforces hard constraints
and that permissive settings cannot leak into production runs.

See ADR-0001, ADR-0002, docs/security/threat-model.md.
"""

from __future__ import annotations

import pytest

from corvusforge.config import ProdConfig
from corvusforge.core.orchestrator import Orchestrator
from corvusforge.core.production_guard import (
    PRODUCTION_REQUIRED_TRUST_KEYS,
    ProductionConfigError,
    enforce_production_constraints,
    production_plugin_load_requires_verification,
    production_waiver_signature_required,
    validate_trust_context_completeness,
)


# A valid production config must supply trust root keys.
_PROD_TRUST_KEYS = {
    "plugin_trust_root": "test-prod-plugin-key-001",
    "waiver_signing_key": "test-prod-waiver-key-002",
}


# ---------------------------------------------------------------------------
# Test: Production guard rejects debug mode
# ---------------------------------------------------------------------------


class TestProductionGuardDebugMode:
    """Production must not run with debug=True."""

    def test_debug_true_in_production_raises(self):
        config = ProdConfig(environment="production", debug=True)
        with pytest.raises(ProductionConfigError, match="debug=True"):
            enforce_production_constraints(config)

    def test_debug_false_in_production_passes(self):
        config = ProdConfig(environment="production", debug=False, **_PROD_TRUST_KEYS)
        enforce_production_constraints(config)  # should not raise

    def test_debug_true_in_development_allowed(self):
        config = ProdConfig(environment="development", debug=True)
        enforce_production_constraints(config)  # guard only applies in production


# ---------------------------------------------------------------------------
# Test: Waiver signature is required in production
# ---------------------------------------------------------------------------


class TestProductionWaiverSignature:
    """Production mode must require waiver signatures."""

    def test_production_requires_signatures(self):
        config = ProdConfig(environment="production")
        assert production_waiver_signature_required(config) is True

    def test_development_does_not_require_signatures(self):
        config = ProdConfig(environment="development")
        assert production_waiver_signature_required(config) is False

    def test_staging_does_not_require_signatures(self):
        config = ProdConfig(environment="staging")
        assert production_waiver_signature_required(config) is False

    def test_orchestrator_in_production_has_strict_waivers(self, tmp_path):
        """The Orchestrator must construct WaiverManager with require_signature=True
        when running in production."""
        config = ProdConfig(environment="production", debug=False, **_PROD_TRUST_KEYS)
        from corvusforge.models.config import PipelineConfig

        pipeline_config = PipelineConfig(
            ledger_db_path=tmp_path / "ledger.db",
            artifact_store_path=tmp_path / "artifacts",
        )
        orch = Orchestrator(config=pipeline_config, prod_config=config)
        assert orch.waiver_manager._require_signature is True

    def test_orchestrator_in_development_has_permissive_waivers(self, tmp_path):
        """Development mode should have permissive waiver settings."""
        config = ProdConfig(environment="development")
        from corvusforge.models.config import PipelineConfig

        pipeline_config = PipelineConfig(
            ledger_db_path=tmp_path / "ledger.db",
            artifact_store_path=tmp_path / "artifacts",
        )
        orch = Orchestrator(config=pipeline_config, prod_config=config)
        assert orch.waiver_manager._require_signature is False


# ---------------------------------------------------------------------------
# Test: Plugin verification in production
# ---------------------------------------------------------------------------


class TestProductionPluginVerification:
    """Production mode must require plugin verification."""

    def test_production_requires_plugin_verification(self):
        config = ProdConfig(environment="production")
        assert production_plugin_load_requires_verification(config) is True

    def test_development_allows_unverified_plugins(self):
        config = ProdConfig(environment="development")
        assert production_plugin_load_requires_verification(config) is False


# ---------------------------------------------------------------------------
# Test: Fail-closed verification never returns True on error
# ---------------------------------------------------------------------------


class TestVerificationNeverAutoPromotes:
    """Assert that verification errors never result in verified=True.

    This is a structural assertion for ADR-0001: the only path to
    verified=True is successful cryptographic verification.
    """

    def test_plugin_verify_returns_false_without_crypto(self, tmp_path):
        """Without saoe-core, verify_plugin must return False."""
        from corvusforge.plugins.registry import PluginRegistry

        registry = PluginRegistry(registry_path=tmp_path / "registry.json")
        result = registry.verify_plugin("nonexistent-plugin")
        assert result is False

    def test_dlc_verify_returns_false_without_crypto(self, tmp_path):
        """Without saoe-core, verify_dlc must return False."""
        from corvusforge.plugins.loader import PluginLoader

        loader = PluginLoader(plugins_dir=tmp_path)
        result = loader.verify_dlc(tmp_path / "nonexistent.dlc")
        assert result is False

    def test_waiver_signature_verify_returns_false_for_unsigned(self):
        """An unsigned waiver must verify as False."""
        from datetime import datetime, timedelta, timezone

        from corvusforge.core.waiver_manager import WaiverManager
        from corvusforge.models.waivers import RiskClassification, WaiverArtifact

        waiver = WaiverArtifact(
            scope="test_scope",
            justification="test",
            expiration=datetime.now(timezone.utc) + timedelta(hours=1),
            approving_identity="test-approver",
            risk_classification=RiskClassification.LOW,
            signature="",  # unsigned
        )
        result = WaiverManager._verify_waiver_signature(waiver)
        assert result is False

    def test_waiver_signature_verify_returns_false_for_garbage(self):
        """A waiver with a garbage signature must verify as False."""
        from datetime import datetime, timedelta, timezone

        from corvusforge.core.waiver_manager import WaiverManager
        from corvusforge.models.waivers import RiskClassification, WaiverArtifact

        waiver = WaiverArtifact(
            scope="test_scope",
            justification="test",
            expiration=datetime.now(timezone.utc) + timedelta(hours=1),
            approving_identity="test-approver",
            risk_classification=RiskClassification.LOW,
            signature="AAAA_not_a_real_signature_ZZZZ",
        )
        result = WaiverManager._verify_waiver_signature(waiver)
        assert result is False


# ---------------------------------------------------------------------------
# Test: Production guard at Orchestrator level
# ---------------------------------------------------------------------------


class TestOrchestratorProductionGuard:
    """The Orchestrator must refuse to start with invalid production config."""

    def test_production_debug_blocks_orchestrator(self, tmp_path):
        """Orchestrator.__init__ must raise if production + debug=True."""
        config = ProdConfig(environment="production", debug=True, **_PROD_TRUST_KEYS)
        from corvusforge.models.config import PipelineConfig

        pipeline_config = PipelineConfig(
            ledger_db_path=tmp_path / "ledger.db",
            artifact_store_path=tmp_path / "artifacts",
        )
        with pytest.raises(ProductionConfigError):
            Orchestrator(config=pipeline_config, prod_config=config)

    def test_development_debug_allows_orchestrator(self, tmp_path):
        """Development + debug=True should work fine."""
        config = ProdConfig(environment="development", debug=True)
        from corvusforge.models.config import PipelineConfig

        pipeline_config = PipelineConfig(
            ledger_db_path=tmp_path / "ledger.db",
            artifact_store_path=tmp_path / "artifacts",
        )
        orch = Orchestrator(config=pipeline_config, prod_config=config)
        assert orch is not None


# ---------------------------------------------------------------------------
# Test: Trust context required keys enforcement
# ---------------------------------------------------------------------------


class TestTrustContextRequiredKeys:
    """Production must have all required trust root keys configured."""

    def test_production_missing_plugin_trust_root_raises(self):
        """Missing plugin_trust_root in production must fail."""
        config = ProdConfig(
            environment="production",
            plugin_trust_root="",
            waiver_signing_key="some-key",
        )
        with pytest.raises(ProductionConfigError, match="plugin_trust_root"):
            enforce_production_constraints(config)

    def test_production_missing_waiver_signing_key_raises(self):
        """Missing waiver_signing_key in production must fail."""
        config = ProdConfig(
            environment="production",
            plugin_trust_root="some-key",
            waiver_signing_key="",
        )
        with pytest.raises(ProductionConfigError, match="waiver_signing_key"):
            enforce_production_constraints(config)

    def test_production_missing_both_keys_reports_both(self):
        """Both missing keys should appear in the error."""
        config = ProdConfig(environment="production")
        with pytest.raises(ProductionConfigError) as exc_info:
            enforce_production_constraints(config)
        assert "plugin_trust_root" in str(exc_info.value)
        assert "waiver_signing_key" in str(exc_info.value)

    def test_production_all_keys_configured_passes(self):
        """All required keys present must pass."""
        config = ProdConfig(environment="production", **_PROD_TRUST_KEYS)
        enforce_production_constraints(config)  # should not raise

    def test_custom_required_keys_override_defaults(self):
        """Custom trust_context_required_keys replaces the default list."""
        config = ProdConfig(
            environment="production",
            anchor_key="my-anchor-key",
            trust_context_required_keys=["anchor_key"],
            # plugin_trust_root and waiver_signing_key are empty,
            # but not in the custom required list
        )
        enforce_production_constraints(config)  # should not raise

    def test_custom_required_keys_missing_value_raises(self):
        """Custom required key without value must still fail."""
        config = ProdConfig(
            environment="production",
            trust_context_required_keys=["anchor_key"],
            anchor_key="",
        )
        with pytest.raises(ProductionConfigError, match="anchor_key"):
            enforce_production_constraints(config)

    def test_development_ignores_required_keys(self):
        """Development mode should not enforce trust root keys."""
        config = ProdConfig(environment="development")
        enforce_production_constraints(config)  # should not raise

    def test_default_required_keys_match_constant(self):
        """Verify the constant matches expected defaults."""
        assert "plugin_trust_root" in PRODUCTION_REQUIRED_TRUST_KEYS
        assert "waiver_signing_key" in PRODUCTION_REQUIRED_TRUST_KEYS


# ---------------------------------------------------------------------------
# Test: validate_trust_context_completeness (runtime check)
# ---------------------------------------------------------------------------


class TestValidateTrustContextCompleteness:
    """Runtime trust context validation for monitor health checks."""

    def test_complete_context_returns_no_warnings(self):
        """All fingerprints present means healthy."""
        ctx = {
            "plugin_trust_root_fp": "aabb112233445566",
            "waiver_signing_key_fp": "ccdd112233445566",
            "anchor_key_fp": "",
        }
        warnings = validate_trust_context_completeness(ctx)
        assert warnings == []

    def test_missing_plugin_fingerprint_warns(self):
        """Empty plugin fingerprint triggers a warning."""
        ctx = {
            "plugin_trust_root_fp": "",
            "waiver_signing_key_fp": "ccdd112233445566",
            "anchor_key_fp": "",
        }
        warnings = validate_trust_context_completeness(ctx)
        assert len(warnings) == 1
        assert "plugin_trust_root_fp" in warnings[0]

    def test_missing_both_fingerprints_warns_twice(self):
        """Both empty fingerprints produce two warnings."""
        ctx = {
            "plugin_trust_root_fp": "",
            "waiver_signing_key_fp": "",
            "anchor_key_fp": "",
        }
        warnings = validate_trust_context_completeness(ctx)
        assert len(warnings) == 2

    def test_custom_required_keys(self):
        """Custom required keys check different fingerprints."""
        ctx = {
            "plugin_trust_root_fp": "aabb",
            "waiver_signing_key_fp": "",
            "anchor_key_fp": "",
        }
        # Only require anchor_key — which is empty
        warnings = validate_trust_context_completeness(
            ctx, required_keys=["anchor_key"]
        )
        assert len(warnings) == 1
        assert "anchor_key_fp" in warnings[0]

    def test_empty_context_warns_for_defaults(self):
        """Completely empty context fails default checks."""
        warnings = validate_trust_context_completeness({})
        assert len(warnings) == 2
