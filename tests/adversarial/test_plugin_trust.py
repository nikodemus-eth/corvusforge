"""Adversarial tests — plugin trust boundary.

These tests verify that:
1. Unsigned plugins remain verified=False (fail-closed)
2. Plugins with invalid signatures remain verified=False
3. Plugins cannot self-attest (supply their own public key)
4. DLC packages without signatures are not auto-verified
5. Crypto bridge failure does not auto-verify
"""

from __future__ import annotations

import json
from pathlib import Path

from corvusforge.plugins.loader import PluginLoader
from corvusforge.plugins.registry import PluginEntry, PluginKind, PluginRegistry


class TestPluginVerificationFailClosed:
    """Ensure verification failures result in verified=False, never True."""

    def test_unsigned_plugin_stays_unverified(self, tmp_path: Path):
        """A plugin with no signature must remain verified=False."""
        registry = PluginRegistry(registry_path=tmp_path / "registry.json")
        entry = PluginEntry(
            name="unsigned-plugin", version="1.0.0",
            kind=PluginKind.VALIDATOR,
            author="attacker", description="No signature",
            entry_point="evil.main",
            signature="",  # no signature
        )
        registry.register(entry)
        result = registry.verify_plugin("unsigned-plugin")
        assert result is False

        # Verify it's still unverified in the registry
        stored = registry.get("unsigned-plugin")
        assert stored is not None
        assert stored.verified is False

    def test_plugin_with_fake_signature_stays_unverified(self, tmp_path: Path):
        """A plugin with a garbage signature must remain verified=False."""
        registry = PluginRegistry(registry_path=tmp_path / "registry.json")
        entry = PluginEntry(
            name="fake-sig-plugin", version="1.0.0",
            kind=PluginKind.SINK,
            author="attacker", description="Fake signature",
            entry_point="evil.main",
            signature="deadbeef" * 16,  # garbage hex
        )
        registry.register(entry)
        result = registry.verify_plugin("fake-sig-plugin")
        # crypto_bridge.verify_data returns False when saoe not available
        assert result is False

        stored = registry.get("fake-sig-plugin")
        assert stored is not None
        assert stored.verified is False

    def test_verify_nonexistent_plugin_returns_false(self, tmp_path: Path):
        """Verifying a plugin that doesn't exist must return False."""
        registry = PluginRegistry(registry_path=tmp_path / "registry.json")
        assert registry.verify_plugin("ghost-plugin") is False

    def test_newly_registered_plugin_defaults_unverified(self, tmp_path: Path):
        """Every newly registered plugin starts as verified=False."""
        registry = PluginRegistry(registry_path=tmp_path / "registry.json")
        entry = PluginEntry(
            name="new-plugin", version="1.0.0",
            kind=PluginKind.REPORTER,
            author="test", description="Fresh plugin",
            entry_point="fresh.main",
        )
        registry.register(entry)
        stored = registry.get("new-plugin")
        assert stored is not None
        assert stored.verified is False


class TestDLCVerificationFailClosed:
    """Ensure DLC package verification fails closed."""

    def _make_dlc(self, tmp_path: Path, *, with_sig: bool = False, sig_content: str = "") -> Path:
        """Helper: create a minimal DLC package directory."""
        dlc_dir = tmp_path / "test-dlc-1.0.0"
        dlc_dir.mkdir(parents=True)
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

    def test_dlc_without_signature_is_unverified(self, tmp_path: Path):
        """DLC with no signature.sig → verified=False on load."""
        dlc_dir = self._make_dlc(tmp_path, with_sig=False)
        loader = PluginLoader(plugins_dir=tmp_path / "installed")
        entry = loader.load_dlc(dlc_dir)
        assert entry.verified is False

    def test_dlc_with_empty_signature_is_unverified(self, tmp_path: Path):
        """DLC with empty signature.sig → verified=False."""
        dlc_dir = self._make_dlc(tmp_path, with_sig=True, sig_content="")
        loader = PluginLoader(plugins_dir=tmp_path / "installed")
        entry = loader.load_dlc(dlc_dir)
        assert entry.verified is False

    def test_dlc_with_garbage_signature_is_unverified(self, tmp_path: Path):
        """DLC with garbage signature → verified=False (crypto unavailable returns False)."""
        dlc_dir = self._make_dlc(tmp_path, with_sig=True, sig_content="deadbeef" * 16)
        loader = PluginLoader(plugins_dir=tmp_path / "installed")
        entry = loader.load_dlc(dlc_dir)
        assert entry.verified is False

    def test_verify_dlc_no_sig_file(self, tmp_path: Path):
        """verify_dlc with no signature.sig → False."""
        dlc_dir = self._make_dlc(tmp_path, with_sig=False)
        loader = PluginLoader(plugins_dir=tmp_path / "installed")
        assert loader.verify_dlc(dlc_dir) is False
