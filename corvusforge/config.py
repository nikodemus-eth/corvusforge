"""Production configuration — env-driven, SAOE-aware.

v0.3.0: Centralized config using pydantic-settings for environment variable
support. Reads from .env file and CORVUSFORGE_* environment variables.

Invariant 16: Production hardening — config, observability, deterministic.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class ProdConfig(BaseSettings):
    """Production configuration with environment variable overrides.

    All settings can be overridden via CORVUSFORGE_* environment variables
    or a .env file in the project root.

    Examples
    --------
    Override via environment::

        export CORVUSFORGE_ENVIRONMENT=staging
        export CORVUSFORGE_LOG_LEVEL=DEBUG
        export CORVUSFORGE_LEDGER_PATH=/data/ledger.db

    Or via .env file::

        CORVUSFORGE_ENVIRONMENT=production
        CORVUSFORGE_DOCKER_MODE=true
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CORVUSFORGE_",
        env_file_encoding="utf-8",
    )

    # Runtime environment
    environment: str = "development"
    log_level: str = "INFO"
    debug: bool = False

    # Storage paths
    ledger_path: Path = Path(".corvusforge/ledger.db")
    artifact_store_path: Path = Path(".corvusforge/artifacts")
    thingstead_data: Path = Path(".openclaw-data")
    plugins_path: Path = Path(".corvusforge/plugins")
    marketplace_path: Path = Path(".corvusforge/marketplace")

    # SAOE integration
    saoe_bucket_prefix: str = "saoi://corvusforge/"
    saoe_core_path: Path | None = None

    # Docker and deployment
    docker_mode: bool = False
    host: str = "0.0.0.0"
    port: int = 8501

    # Fleet settings
    max_concurrent_fleets: int = 8
    fleet_timeout_seconds: int = 300

    # Trust roots — public keys (hex) for signing verification
    # Set via CORVUSFORGE_PLUGIN_TRUST_ROOT, etc.
    plugin_trust_root: str = ""    # public key for plugin signature verification
    waiver_signing_key: str = ""   # public key for waiver signature verification
    anchor_key: str = ""           # public key for anchor signing (future)

    # Observability
    enable_metrics: bool = False
    metrics_port: int = 9090

    @property
    def is_production(self) -> bool:
        """Whether running in production mode."""
        return self.environment == "production"


# Module-level singleton — import as `from corvusforge.config import config`
config = ProdConfig()
