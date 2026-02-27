# Corvusforge

Deterministic, Auditable, Contract-Driven Coding Pipeline with SAOE integration.

## Identity

Corvusforge is a 10-stage pipeline orchestrator that enforces 16 core invariants across every run. Every state transition is recorded in an append-only, hash-chained Run Ledger. Every artifact is content-addressed and immutable. Every plugin is Ed25519-signed.

**Version:** 0.4.0
**License:** AGPL-3.0-only
**Author:** CORVUSFORGE, LLC

## Architecture

```
corvusforge/
  bridge/         # Adapters: crypto, audit, transport, SAOE
  cli/            # Typer CLI (corvusforge new|demo|monitor|plugins|ui)
  contrib/        # User contribution hooks + decision registry
  core/           # Orchestrator, RunLedger, StageMachine, ArtifactStore
  dashboard/      # Streamlit Build Monitor 2.0
  marketplace/    # Local-first DLC marketplace (signed)
  models/         # Pydantic models (frozen, validated)
  monitor/        # Projection + Rich terminal renderer
  plugins/        # DLC plugin loader + registry
  routing/        # SinkDispatcher + sink backends
  stages/         # BaseStage + 10 concrete stages (s0-s7 + s55 + s575)
  thingstead/     # Fleet management, executors, persistent memory
```

## Key Subsystems

- **RunLedger** (`core/run_ledger.py`): SQLite-backed, hash-chained, append-only. Trust context sealed into every entry.
- **StageMachine** (`core/stage_machine.py`): Enforces valid state transitions. Prerequisites checked before every run.
- **CryptoBridge** (`bridge/crypto_bridge.py`): Three-tier signing: saoe-core > PyNaCl (Ed25519) > fail-closed.
- **ThingsteadFleet** (`thingstead/fleet.py`): Agent pool with Protocol-based pluggable executors and tool gates.
- **Transport** (`bridge/transport.py`): SQLite-backed persistent queue (or in-memory fallback).
- **Marketplace** (`marketplace/marketplace.py`): Publish, verify (Ed25519), install DLC plugins.

## Security Model

- **Fail-closed crypto**: `verify_data()` returns `False` unless cryptographic proof succeeds.
- **Trust context**: Key fingerprints recorded in every ledger entry for forensic auditability.
- **Plugin verification**: Ed25519 signatures via PyNaCl. Unsigned = unverified = untrusted.
- **Waiver enforcement**: Waivers require signed authorization to bypass mandatory gates.
- **Production guard**: Enforces trust root key configuration before pipeline execution.

## Build & Test

```bash
# Install (development)
pip install -e ".[dev]"

# Run tests
pytest                     # Full suite (387 tests)
pytest --tb=short -q       # Quick summary
pytest tests/unit/         # Unit tests only
pytest tests/adversarial/  # Adversarial tests only

# CLI
corvusforge --help
corvusforge demo           # End-to-end demo
corvusforge ui             # Streamlit dashboard

# Docker
docker build -t corvusforge:0.4.0 .
docker run corvusforge:0.4.0
```

## Test Conventions

- **TDD**: All features developed test-first (RED-GREEN-REFACTOR)
- **Test layout**: `tests/unit/`, `tests/adversarial/`, `tests/integration/`
- **Naming**: `test_{module}.py` with descriptive class and method names
- **Models**: Use concrete envelope subclasses (`EventEnvelope`, `WorkOrderEnvelope`), not `EnvelopeBase` directly
- **Required fields**: `EventEnvelope` requires `stage_id`, `source_node_id`, `destination_node_id`
- **Temp paths**: Use `tmp_path` fixture for any filesystem-touching tests

## saoe-core Situation

`saoe-core` and `saoe-openclaw` are unpublished packages. All saoe-core integration points use try-import patterns:
- If saoe-core is installed: full SATL transport, Keyring crypto, AuditLog dual-write
- If absent: PyNaCl crypto, SQLite transport, RunLedger-only audit

The codebase is fully functional without saoe-core. All saoe-core paths are guarded with availability flags (`is_saoe_crypto_available()`, `is_saoe_satl_available()`, etc.).

## Dependencies

- **Core**: `pydantic>=2.0`, `PyNaCl>=1.5.0`, `typer[all]>=0.9`, `rich>=13.0`
- **Dashboard**: `streamlit>=1.30`
- **Dev**: `pytest>=8.0`, `pytest-cov`
