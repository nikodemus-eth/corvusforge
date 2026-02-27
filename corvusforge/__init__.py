"""Corvusforge: Deterministic, Auditable, Contract-Driven Coding Pipeline.

v0.4.0 — Real crypto, pluggable executors, persistent transport:
  - Real Ed25519 crypto via PyNaCl (three-tier: saoe-core > PyNaCl > fail-closed)
  - Pluggable agent executors (Protocol-based with AllowlistToolGate)
  - SQLite-backed persistent transport queue
  - Marketplace Ed25519 signature verification
  - 10-stage pipeline (0->7 including 5.5 accessibility + 5.75 security gates)
  - Thingstead fleet with Protocol executors (Invariant 11)
  - Persistent memory in .openclaw-data (Invariant 12)
  - Signed DLC plugins via ToolGate + SATL (Invariant 13)
  - Full Multi-Agent UI / Streamlit dashboard (Invariant 14)
  - DLC Marketplace, local-first + signed (Invariant 15)
  - Production hardening: Docker, CI/CD, env-driven config, observability (Invariant 16)
  - 387 tests (unit + adversarial + integration)
"""

__version__ = "0.4.0"
__author__ = "CORVUSFORGE, LLC"
__description__ = (
    "Deterministic, Auditable, Contract-Driven Coding Pipeline with SAOE integration"
)

from corvusforge.core.orchestrator import Orchestrator
from corvusforge.monitor.projection import MonitorProjection as BuildMonitor
from corvusforge.cli.app import app as cli

__all__ = ["Orchestrator", "BuildMonitor", "cli", "__version__"]
