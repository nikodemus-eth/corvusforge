"""Adversarial tests — trust root enforcement across all trust boundaries.

F2: Waiver verification must use the configured trust root key, not the
    self-selected approving_identity.
F3: DLC load/install must refuse unverified plugins in production mode.
F1: Plugin verification must use the configured plugin trust root, not
    a plugin-supplied public key.
F4: Marketplace listing verification must fail-closed when crypto is
    unavailable or an exception occurs (no more fail-open).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from corvusforge.core.artifact_store import ContentAddressedStore
from corvusforge.core.waiver_manager import (
    WaiverManager,
    WaiverSignatureError,
)
from corvusforge.marketplace.marketplace import Marketplace
from corvusforge.models.waivers import RiskClassification, WaiverArtifact
from corvusforge.plugins.loader import PluginLoader, PluginVerificationError
from corvusforge.plugins.registry import PluginEntry, PluginKind, PluginRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_waiver(
    scope: str = "s55_accessibility",
    signature: str = "",
    approving_identity: str = "some-reviewer",
    hours_valid: int = 24,
) -> WaiverArtifact:
    return WaiverArtifact(
        scope=scope,
        justification="Test waiver",
        expiration=datetime.now(timezone.utc) + timedelta(hours=hours_valid),
        approving_identity=approving_identity,
        risk_classification=RiskClassification.LOW,
        signature=signature,
    )


def _make_dlc(tmp_path: Path, *, with_sig: bool = False, sig_content: str = "") -> Path:
    dlc_dir = tmp_path / "test-dlc-1.0.0"
    dlc_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": "test-dlc", "version": "1.0.0",
        "author": "test", "description": "Test DLC",
        "entry_point": "plugin.main", "kind": "validator",
    }
    (dlc_dir / "manifest.json").write_text(json.dumps(manifest))
    (dlc_dir / "plugin.py").write_text("def main(): pass")
    if with_sig:
        (dlc_dir / "signature.sig").write_text(sig_content)
    return dlc_dir


# ===================================================================
# F2: Waiver trust root enforcement
# ===================================================================

class TestWaiverTrustRootEnforcement:
    """Waivers must verify against the configured waiver_verification_key,
    NOT against waiver.approving_identity."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> ContentAddressedStore:
        return ContentAddressedStore(tmp_path / "artifacts")

    def test_waiver_manager_accepts_verification_key_param(self, store):
        """WaiverManager must accept a waiver_verification_key kwarg."""
        mgr = WaiverManager(
            store,
            require_signature=True,
            waiver_verification_key="some-public-key-hex",
        )
        assert mgr._waiver_verification_key == "some-public-key-hex"

    def test_empty_verification_key_fails_closed(self, store):
        """When waiver_verification_key is empty, signature verification
        must return False (fail-closed), even if the waiver has a signature."""
        mgr = WaiverManager(
            store,
            require_signature=True,
            waiver_verification_key="",
        )
        waiver = _make_waiver(signature="deadbeef" * 16)
        # Should raise because empty key → verification fails → signature invalid
        with pytest.raises(WaiverSignatureError, match="no valid signature"):
            mgr.register_waiver(waiver)

    def test_self_selected_identity_does_not_validate(self, store):
        """approving_identity is informational only — it must NOT be used
        as the verification key. Even if the waiver is 'signed' against
        its own approving_identity, that's attacker-controlled."""
        mgr = WaiverManager(
            store,
            require_signature=True,
            waiver_verification_key="trusted-org-key-hex",
        )
        # Waiver claims approving_identity is the key, but config says otherwise
        waiver = _make_waiver(
            signature="deadbeef" * 16,
            approving_identity="attacker-public-key",
        )
        # Should fail — the signature must verify against config key, not identity
        with pytest.raises(WaiverSignatureError, match="no valid signature"):
            mgr.register_waiver(waiver)

    def test_valid_signature_with_config_key_succeeds(self, store):
        """When the signature verifies against waiver_verification_key,
        the waiver is accepted."""
        mgr = WaiverManager(
            store,
            require_signature=True,
            waiver_verification_key="trusted-key",
        )
        waiver = _make_waiver(signature="valid-sig-hex")

        # Mock verify_data to return True when called with the config key
        verify_path = (
            "corvusforge.core.waiver_manager"
            ".WaiverManager._verify_waiver_signature"
        )
        with patch(verify_path) as mock_verify:
            mock_verify.return_value = True
            addr = mgr.register_waiver(waiver)
            assert addr.startswith("sha256:")
            assert mgr.has_valid_waiver("s55_accessibility") is True


# ===================================================================
# F3: DLC load/install refuses unverified in production
# ===================================================================

class TestDLCProductionVerificationEnforcement:
    """In production, unverified DLC must not be loadable."""

    def test_loader_accepts_require_verified_param(self, tmp_path: Path):
        """PluginLoader must accept a require_verified kwarg."""
        loader = PluginLoader(
            plugins_dir=tmp_path / "installed",
            require_verified=True,
        )
        assert loader._require_verified is True

    def test_unverified_dlc_raises_in_require_verified_mode(self, tmp_path: Path):
        """When require_verified=True, loading an unverified DLC must raise."""
        dlc_dir = _make_dlc(tmp_path, with_sig=False)
        loader = PluginLoader(
            plugins_dir=tmp_path / "installed",
            require_verified=True,
        )
        with pytest.raises(PluginVerificationError, match="failed verification"):
            loader.load_dlc(dlc_dir)

    def test_unverified_dlc_loads_when_not_required(self, tmp_path: Path):
        """When require_verified=False, unverified DLC loads with verified=False."""
        dlc_dir = _make_dlc(tmp_path, with_sig=False)
        loader = PluginLoader(
            plugins_dir=tmp_path / "installed",
            require_verified=False,
        )
        entry = loader.load_dlc(dlc_dir)
        assert entry.verified is False

    def test_install_dlc_also_enforces_verification(self, tmp_path: Path):
        """install_dlc delegates to load_dlc, so enforcement propagates."""
        dlc_dir = _make_dlc(tmp_path, with_sig=False)
        loader = PluginLoader(
            plugins_dir=tmp_path / "installed",
            require_verified=True,
        )
        with pytest.raises(PluginVerificationError, match="failed verification"):
            loader.install_dlc(dlc_dir)

    def test_plugin_verification_error_is_importable(self):
        """PluginVerificationError must be importable from loader module."""
        from corvusforge.plugins.loader import PluginVerificationError
        assert issubclass(PluginVerificationError, RuntimeError)


# ===================================================================
# F1: Plugin registry trust root enforcement
# ===================================================================

class TestPluginRegistryTrustRoot:
    """Plugin verification must use a configured trust root key, not
    a plugin-supplied public key from entry.metadata."""

    def test_registry_accepts_trust_root_key_param(self, tmp_path: Path):
        """PluginRegistry must accept a plugin_trust_root_key kwarg."""
        registry = PluginRegistry(
            registry_path=tmp_path / "registry.json",
            plugin_trust_root_key="configured-trust-root-hex",
        )
        assert registry._plugin_trust_root_key == "configured-trust-root-hex"

    def test_plugin_supplied_key_is_ignored(self, tmp_path: Path):
        """A plugin that ships its own public_key in metadata must NOT
        use that key for verification — the trust root comes from config."""
        registry = PluginRegistry(
            registry_path=tmp_path / "registry.json",
            plugin_trust_root_key="real-trust-root",
        )
        entry = PluginEntry(
            name="evil-plugin", version="1.0.0",
            kind=PluginKind.SINK,
            author="attacker", description="Self-signed evil",
            entry_point="evil.main",
            signature="deadbeef" * 16,
            metadata={"public_key": "attacker-controlled-key"},
        )
        registry.register(entry)
        # Even with a self-supplied key, verification uses the config trust root
        result = registry.verify_plugin("evil-plugin")
        assert result is False  # crypto unavailable → fail-closed

    def test_empty_trust_root_key_fails_closed(self, tmp_path: Path):
        """When no trust root key is configured, verification must fail-closed."""
        registry = PluginRegistry(
            registry_path=tmp_path / "registry.json",
            plugin_trust_root_key="",
        )
        entry = PluginEntry(
            name="signed-plugin", version="1.0.0",
            kind=PluginKind.VALIDATOR,
            author="trusted-author",
            entry_point="module.main",
            signature="abcdef1234567890" * 4,
        )
        registry.register(entry)
        result = registry.verify_plugin("signed-plugin")
        assert result is False


# ===================================================================
# F4: Marketplace fail-open regression
# ===================================================================

class TestMarketplaceFailClosed:
    """Marketplace verification must fail-closed when crypto is unavailable
    or an exception occurs."""

    def _make_published_dlc(self, tmp_path: Path) -> tuple[Marketplace, str]:
        """Publish a DLC and return (marketplace, listing_name)."""
        dlc_dir = tmp_path / "mp-dlc-1.0.0"
        dlc_dir.mkdir(parents=True)
        manifest = {
            "name": "mp-dlc", "version": "1.0.0",
            "author": "test", "description": "Marketplace DLC",
            "entry_point": "plugin.main", "kind": "validator",
        }
        (dlc_dir / "manifest.json").write_text(json.dumps(manifest))
        (dlc_dir / "plugin.py").write_text("def main(): pass")
        (dlc_dir / "signature.sig").write_text("deadbeef" * 16)

        mp = Marketplace(marketplace_dir=tmp_path / "marketplace")
        mp.publish(dlc_dir, author="test")
        return mp, "mp-dlc"

    def test_crypto_unavailable_does_not_mark_verified(self, tmp_path: Path):
        """When crypto bridge is unavailable, listing must NOT be marked verified."""
        mp, name = self._make_published_dlc(tmp_path)
        result = mp.verify_listing(name)
        # Crypto is unavailable in tests → must be False (fail-closed)
        assert result is False
        listing = mp.get_listing(name)
        assert listing is not None
        assert listing.verified is False

    def test_exception_during_verify_does_not_mark_verified(self, tmp_path: Path):
        """When verification throws, listing must NOT be marked verified."""
        mp, name = self._make_published_dlc(tmp_path)

        # The import is inside verify_listing, so we patch at the source
        with patch(
            "corvusforge.bridge.crypto_bridge.is_saoe_crypto_available",
            side_effect=RuntimeError("kaboom"),
        ):
            result = mp.verify_listing(name)
            assert result is False

        listing = mp.get_listing(name)
        assert listing is not None
        assert listing.verified is False

    def test_explicit_verification_failure_marks_unverified(self, tmp_path: Path):
        """When verify_data returns False, listing must NOT be marked verified."""
        mp, name = self._make_published_dlc(tmp_path)

        crypto = "corvusforge.bridge.crypto_bridge"
        with patch(f"{crypto}.is_saoe_crypto_available", return_value=True), \
             patch(f"{crypto}.verify_data", return_value=False):
            result = mp.verify_listing(name)
            assert result is False

        listing = mp.get_listing(name)
        assert listing is not None
        assert listing.verified is False


# ===================================================================
# Structural: all construction sites must pass trust root keys
# ===================================================================

class TestAllConstructionSitesWired:
    """Every PluginRegistry() and WaiverManager() construction in the
    codebase must pass the appropriate trust root key parameter.

    Uses ``ast.parse`` for robust detection that survives formatting changes,
    multi-line calls, nested parentheses, and string literals.
    """

    # Files that construct trust-sensitive objects (production code only).
    _AUDITED_FILES: list[str] = [
        "dashboard/app.py",
        "cli/app.py",
        "core/orchestrator.py",
    ]

    @staticmethod
    def _find_calls_missing_kwarg(
        rel_path: str,
        func_name: str,
        required_kwarg: str,
    ) -> list[int]:
        """Return line numbers where ``func_name(...)`` is called without
        ``required_kwarg`` in its keyword arguments.

        Parses the source with ``ast`` so multi-line calls, nested parens,
        and formatting changes are handled correctly.
        """
        import ast

        import corvusforge

        package_root = Path(corvusforge.__file__).parent
        full_path = package_root / rel_path
        if not full_path.exists():
            return []

        source = full_path.read_text()
        tree = ast.parse(source, filename=str(full_path))
        hits: list[int] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # Match Name (direct call) or Attribute (method call)
            callee = node.func
            name: str | None = None
            if isinstance(callee, ast.Name):
                name = callee.id
            elif isinstance(callee, ast.Attribute):
                name = callee.attr
            if name != func_name:
                continue
            # Check keywords for the required kwarg
            kwarg_names = {kw.arg for kw in node.keywords if kw.arg is not None}
            if required_kwarg not in kwarg_names:
                hits.append(node.lineno)
        return hits

    def test_no_bare_plugin_registry_construction(self):
        """Every PluginRegistry() call must include plugin_trust_root_key=."""
        for rel_path in self._AUDITED_FILES:
            hits = self._find_calls_missing_kwarg(
                rel_path, "PluginRegistry", "plugin_trust_root_key"
            )
            assert hits == [], (
                f"{rel_path} has PluginRegistry() without "
                f"plugin_trust_root_key= on line(s) {hits}"
            )

    def test_no_bare_waiver_manager_construction(self):
        """Every WaiverManager() call must include waiver_verification_key=."""
        for rel_path in [
            "dashboard/app.py",
            "core/orchestrator.py",
        ]:
            hits = self._find_calls_missing_kwarg(
                rel_path, "WaiverManager", "waiver_verification_key"
            )
            assert hits == [], (
                f"{rel_path} has WaiverManager() without "
                f"waiver_verification_key= on line(s) {hits}"
            )


# ===================================================================
# Structural: entrypoints must call enforce_production_constraints
# ===================================================================

class TestEntrypointsRunProductionGuard:
    """Every user-facing entrypoint (CLI, dashboard) must call
    enforce_production_constraints() to fail fast in production."""

    @staticmethod
    def _source_text(rel_path: str) -> str:
        import corvusforge
        package_root = Path(corvusforge.__file__).parent
        full = package_root / rel_path
        return full.read_text() if full.exists() else ""

    def test_cli_entrypoint_calls_production_guard(self):
        """CLI app must call enforce_production_constraints."""
        src = self._source_text("cli/app.py")
        assert "enforce_production_constraints" in src, (
            "cli/app.py does not call enforce_production_constraints — "
            "production mode will not fail fast at CLI startup"
        )

    def test_dashboard_entrypoint_calls_production_guard(self):
        """Dashboard must call enforce_production_constraints."""
        src = self._source_text("dashboard/app.py")
        assert "enforce_production_constraints" in src, (
            "dashboard/app.py does not call enforce_production_constraints — "
            "production mode will not fail fast at dashboard startup"
        )
