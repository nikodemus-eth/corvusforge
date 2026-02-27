"""Tests for production config — env-driven settings."""

from __future__ import annotations

from pathlib import Path

from corvusforge.config import ProdConfig


class TestProdConfig:
    def test_defaults(self):
        config = ProdConfig()
        assert config.environment == "development"
        assert config.log_level == "INFO"
        assert config.max_concurrent_fleets == 8

    def test_is_production_false_by_default(self):
        config = ProdConfig()
        assert config.is_production is False

    def test_is_production_when_set(self):
        config = ProdConfig(environment="production")
        assert config.is_production is True

    def test_default_paths(self):
        config = ProdConfig()
        assert config.ledger_path == Path(".corvusforge/ledger.db")
        assert config.thingstead_data == Path(".openclaw-data")
        assert config.plugins_path == Path(".corvusforge/plugins")

    def test_docker_mode_default(self):
        config = ProdConfig()
        assert config.docker_mode is False
