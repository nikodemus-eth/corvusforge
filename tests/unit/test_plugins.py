"""Tests for Plugin System — registry, loader, DLC packages."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from corvusforge.plugins.registry import PluginRegistry, PluginEntry, PluginKind
from corvusforge.plugins.loader import PluginLoader, DLCPackage, DLCManifest


class TestPluginKind:
    def test_all_kinds(self):
        assert PluginKind.STAGE_EXTENSION == "stage_extension"
        assert PluginKind.SINK == "sink"
        assert PluginKind.VALIDATOR == "validator"
        assert PluginKind.REPORTER == "reporter"
        assert PluginKind.TRANSFORMER == "transformer"


class TestPluginEntry:
    def test_defaults(self):
        entry = PluginEntry(
            name="test-plugin", version="1.0.0",
            kind=PluginKind.VALIDATOR,
            author="test", description="A test plugin",
            entry_point="test_plugin.main",
        )
        assert entry.plugin_id.startswith("plg-")
        assert entry.verified is False
        assert entry.enabled is True

    def test_frozen(self):
        entry = PluginEntry(
            name="test", version="1.0.0",
            kind=PluginKind.SINK,
            author="test", description="Test",
            entry_point="test.main",
        )
        with pytest.raises(Exception):
            entry.name = "changed"


class TestPluginRegistry:
    def test_register_and_get(self, tmp_path: Path):
        registry = PluginRegistry(registry_path=tmp_path / "registry.json")
        entry = PluginEntry(
            name="my-plugin", version="1.0.0",
            kind=PluginKind.VALIDATOR,
            author="test", description="Test plugin",
            entry_point="my_plugin.main",
        )
        plugin_id = registry.register(entry)
        assert plugin_id != ""

        found = registry.get("my-plugin")
        assert found is not None
        assert found.name == "my-plugin"

    def test_list_plugins_by_kind(self, tmp_path: Path):
        registry = PluginRegistry(registry_path=tmp_path / "registry.json")
        registry.register(PluginEntry(
            name="p1", version="1.0", kind=PluginKind.SINK,
            author="a", description="d", entry_point="p1",
        ))
        registry.register(PluginEntry(
            name="p2", version="1.0", kind=PluginKind.VALIDATOR,
            author="a", description="d", entry_point="p2",
        ))

        sinks = registry.list_plugins(kind=PluginKind.SINK)
        assert len(sinks) == 1
        assert sinks[0].name == "p1"

    def test_unregister(self, tmp_path: Path):
        registry = PluginRegistry(registry_path=tmp_path / "registry.json")
        registry.register(PluginEntry(
            name="temp", version="1.0", kind=PluginKind.SINK,
            author="a", description="d", entry_point="t",
        ))
        assert registry.unregister("temp") is True
        assert registry.get("temp") is None

    def test_persist_and_load(self, tmp_path: Path):
        path = tmp_path / "registry.json"
        registry = PluginRegistry(registry_path=path)
        registry.register(PluginEntry(
            name="persistent", version="2.0", kind=PluginKind.REPORTER,
            author="a", description="d", entry_point="p",
        ))

        # Reload
        registry2 = PluginRegistry(registry_path=path)
        found = registry2.get("persistent")
        assert found is not None
        assert found.version == "2.0"

    def test_get_stats(self, tmp_path: Path):
        registry = PluginRegistry(registry_path=tmp_path / "registry.json")
        registry.register(PluginEntry(
            name="p1", version="1.0", kind=PluginKind.SINK,
            author="a", description="d", entry_point="p1",
        ))
        stats = registry.get_stats()
        assert stats["total"] == 1

    def test_version_collision_raises(self, tmp_path: Path):
        registry = PluginRegistry(registry_path=tmp_path / "registry.json")
        registry.register(PluginEntry(
            name="dup", version="1.0", kind=PluginKind.SINK,
            author="a", description="d", entry_point="d",
        ))
        with pytest.raises(ValueError, match="already registered"):
            registry.register(PluginEntry(
                name="dup", version="2.0", kind=PluginKind.SINK,
                author="a", description="d", entry_point="d",
            ))


class TestDLCManifest:
    def test_manifest_defaults(self):
        m = DLCManifest(
            name="test-dlc", version="1.0.0", author="test",
            description="Test DLC", entry_point="plugin.main",
            kind=PluginKind.VALIDATOR,
        )
        assert m.min_corvusforge_version == "0.2.0"
        assert m.dependencies == []

    def test_manifest_frozen(self):
        m = DLCManifest(
            name="test", version="1.0", author="a",
            description="d", entry_point="e",
            kind=PluginKind.SINK,
        )
        with pytest.raises(Exception):
            m.name = "changed"


class TestPluginLoader:
    def test_list_installed_empty(self, tmp_path: Path):
        loader = PluginLoader(plugins_dir=tmp_path / "plugins")
        assert loader.list_installed() == []

    def test_load_dlc_from_directory(self, tmp_path: Path):
        # Create a mock DLC package
        dlc_dir = tmp_path / "test-dlc-1.0.0"
        dlc_dir.mkdir(parents=True)
        manifest = {
            "name": "test-dlc", "version": "1.0.0",
            "author": "test-author", "description": "A test DLC",
            "entry_point": "plugin.main", "kind": "validator",
        }
        (dlc_dir / "manifest.json").write_text(json.dumps(manifest))
        (dlc_dir / "plugin.py").write_text("def main(): pass")

        loader = PluginLoader(plugins_dir=tmp_path / "installed")
        entry = loader.load_dlc(dlc_dir)
        assert entry.name == "test-dlc"
        assert entry.version == "1.0.0"
        assert entry.kind == PluginKind.VALIDATOR
