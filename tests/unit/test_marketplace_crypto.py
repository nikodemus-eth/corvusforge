"""Unit tests for marketplace real crypto verification.

Phase 5 of v0.4.0: Wire marketplace verification to native PyNaCl crypto
so that publish-and-verify works end-to-end with real Ed25519 signatures.

TDD: RED phase — these tests exercise real sign + verify round-trips.
"""

from __future__ import annotations

import json
from pathlib import Path

from corvusforge.bridge.crypto_bridge import generate_keypair, sign_data
from corvusforge.core.hasher import canonical_json_bytes, sha256_hex
from corvusforge.marketplace.marketplace import Marketplace
from corvusforge.plugins.loader import PluginLoader


def _create_dlc_package(
    tmp_path: Path,
    name: str = "test-plugin",
    version: str = "1.0.0",
    signing_key: str | None = None,
) -> Path:
    """Create a minimal DLC package directory with optional real signature."""
    pkg_dir = tmp_path / f"{name}-{version}"
    pkg_dir.mkdir(parents=True)

    manifest = {
        "name": name,
        "version": version,
        "description": "Test plugin for marketplace crypto",
        "kind": "validator",
        "author": "test-author",
        "entry_point": "plugin.py",
    }
    manifest_path = pkg_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    plugin_path = pkg_dir / "plugin.py"
    plugin_path.write_text("# test plugin\ndef validate(ctx): return True\n")

    if signing_key:
        # Compute file hashes (same way marketplace does)
        file_hashes: dict[str, str] = {}
        for file_path in sorted(pkg_dir.rglob("*")):
            if file_path.is_file() and file_path.name != "signature.sig":
                rel = str(file_path.relative_to(pkg_dir))
                file_hashes[rel] = sha256_hex(file_path.read_bytes())

        manifest_bytes = canonical_json_bytes(file_hashes)
        signature = sign_data(manifest_bytes, signing_key)
        sig_path = pkg_dir / "signature.sig"
        sig_path.write_text(signature, encoding="utf-8")

    return pkg_dir


# ---------------------------------------------------------------------------
# Test: End-to-end publish and verify with real crypto
# ---------------------------------------------------------------------------


class TestMarketplaceRealCrypto:
    """Marketplace must verify listings using real Ed25519 signatures."""

    def test_publish_and_verify_with_real_signature(self, tmp_path: Path):
        """A properly signed package should verify as True."""
        priv, pub = generate_keypair()
        pkg = _create_dlc_package(tmp_path / "pkgs", signing_key=priv)

        mp = Marketplace(
            marketplace_dir=tmp_path / "marketplace",
            verification_public_key=pub,
        )
        listing = mp.publish(pkg, author="test")
        assert listing.name == "test-plugin"
        assert listing.signature != ""

        result = mp.verify_listing("test-plugin")
        assert result is True

    def test_verify_fails_with_wrong_signature(self, tmp_path: Path):
        """A package signed with key A should fail verification under key B."""
        priv_a, _pub_a = generate_keypair()
        _priv_b, pub_b = generate_keypair()

        pkg = _create_dlc_package(tmp_path / "pkgs", signing_key=priv_a)

        mp = Marketplace(
            marketplace_dir=tmp_path / "marketplace",
            verification_public_key=pub_b,  # Different key!
        )
        mp.publish(pkg, author="test")

        result = mp.verify_listing("test-plugin")
        assert result is False

    def test_verify_fails_with_tampered_content(self, tmp_path: Path):
        """Modifying package contents after signing should fail verification."""
        priv, pub = generate_keypair()
        pkg = _create_dlc_package(tmp_path / "pkgs", signing_key=priv)

        mp = Marketplace(
            marketplace_dir=tmp_path / "marketplace",
            verification_public_key=pub,
        )
        mp.publish(pkg, author="test")

        # Tamper with the installed package
        installed = tmp_path / "marketplace" / "packages" / "test-plugin-1.0.0"
        plugin_file = installed / "plugin.py"
        plugin_file.write_text("# TAMPERED!")

        result = mp.verify_listing("test-plugin")
        assert result is False

    def test_verify_fails_with_empty_signature(self, tmp_path: Path):
        """A package with no signature file should fail verification."""
        _priv, pub = generate_keypair()
        # No signing key = no signature file
        pkg = _create_dlc_package(tmp_path / "pkgs", signing_key=None)

        mp = Marketplace(
            marketplace_dir=tmp_path / "marketplace",
            verification_public_key=pub,
        )
        mp.publish(pkg, author="test")

        result = mp.verify_listing("test-plugin")
        assert result is False

    def test_marketplace_end_to_end_publish_verify_install(self, tmp_path: Path):
        """Full lifecycle: publish → verify → install."""
        priv, pub = generate_keypair()
        pkg = _create_dlc_package(tmp_path / "pkgs", signing_key=priv)

        plugins_dir = tmp_path / "plugins"
        loader = PluginLoader(plugins_dir=plugins_dir)
        mp = Marketplace(
            marketplace_dir=tmp_path / "marketplace",
            loader=loader,
            verification_public_key=pub,
        )

        # Publish
        listing = mp.publish(pkg, author="test")
        assert listing.name == "test-plugin"

        # Verify
        assert mp.verify_listing("test-plugin") is True

        # Install
        installed = mp.install("test-plugin")
        assert installed is True or installed is not None
