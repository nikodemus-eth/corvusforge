"""Tests for DLC Marketplace — listings, publish, search."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from corvusforge.marketplace.marketplace import Marketplace, MarketplaceListing
from corvusforge.plugins.registry import PluginKind


class TestMarketplaceListing:
    def test_defaults(self):
        listing = MarketplaceListing(
            name="test-plugin", version="1.0.0",
            author="test", description="A test listing",
            kind=PluginKind.VALIDATOR,
            content_address="sha256:abc123",
            signature="",
        )
        assert listing.listing_id.startswith("mkt-")
        assert listing.downloads == 0
        assert listing.verified is False

    def test_frozen(self):
        listing = MarketplaceListing(
            name="test", version="1.0", author="a",
            description="d", kind=PluginKind.SINK,
            content_address="sha256:abc", signature="",
        )
        with pytest.raises(Exception):
            listing.name = "changed"


class TestMarketplace:
    def test_empty_marketplace(self, tmp_path: Path):
        mp = Marketplace(marketplace_dir=tmp_path / "marketplace")
        assert mp.list_all() == []
        assert mp.get_stats()["total"] == 0

    def test_search_empty(self, tmp_path: Path):
        mp = Marketplace(marketplace_dir=tmp_path / "marketplace")
        results = mp.search("anything")
        assert results == []

    def test_persist_and_load_catalog(self, tmp_path: Path):
        mp_dir = tmp_path / "marketplace"
        mp = Marketplace(marketplace_dir=mp_dir)
        listing = MarketplaceListing(
            name="test-plugin", version="1.0.0",
            author="tester", description="Test",
            kind=PluginKind.VALIDATOR,
            content_address="sha256:abc", signature="",
        )
        mp._listings["test-plugin"] = listing
        mp.persist_catalog()

        # Reload
        mp2 = Marketplace(marketplace_dir=mp_dir)
        assert mp2.get_listing("test-plugin") is not None

    def test_publish_from_dlc_directory(self, tmp_path: Path):
        """Test publishing a DLC package to the marketplace."""
        dlc_dir = tmp_path / "my-dlc-1.0.0"
        dlc_dir.mkdir(parents=True)
        manifest = {
            "name": "my-dlc", "version": "1.0.0",
            "author": "tester", "description": "A marketplace DLC",
            "entry_point": "plugin.main", "kind": "validator",
        }
        (dlc_dir / "manifest.json").write_text(json.dumps(manifest))
        (dlc_dir / "plugin.py").write_text("def main(): pass")

        mp = Marketplace(marketplace_dir=tmp_path / "marketplace")
        listing = mp.publish(dlc_dir, author="tester", tags=["test"])
        assert listing.name == "my-dlc"
        assert listing.content_address.startswith("sha256:")
        assert "test" in listing.tags

    def test_search_by_name(self, tmp_path: Path):
        mp = Marketplace(marketplace_dir=tmp_path / "marketplace")
        listing = MarketplaceListing(
            name="accessibility-checker", version="1.0",
            author="a", description="WCAG checks",
            kind=PluginKind.VALIDATOR,
            content_address="sha256:abc", signature="",
        )
        mp._listings["accessibility-checker"] = listing

        results = mp.search("accessibility")
        assert len(results) == 1
        assert results[0].name == "accessibility-checker"

    def test_search_by_kind(self, tmp_path: Path):
        mp = Marketplace(marketplace_dir=tmp_path / "marketplace")
        mp._listings["p1"] = MarketplaceListing(
            name="p1", version="1.0", author="a", description="d",
            kind=PluginKind.SINK, content_address="sha256:a", signature="",
        )
        mp._listings["p2"] = MarketplaceListing(
            name="p2", version="1.0", author="a", description="d",
            kind=PluginKind.VALIDATOR, content_address="sha256:b", signature="",
        )

        sinks = mp.search(kind=PluginKind.SINK)
        assert len(sinks) == 1
        assert sinks[0].name == "p1"
