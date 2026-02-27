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
    ProductionConfigError,
    enforce_production_constraints,
    production_plugin_load_requires_verification,
    production_waiver_signature_required,
)


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
        config = ProdConfig(environment="production", debug=False)
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
        config = ProdConfig(environment="production", debug=False)
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
        config = ProdConfig(environment="production", debug=True)
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
