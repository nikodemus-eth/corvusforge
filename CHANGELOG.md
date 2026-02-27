# Corvusforge Changelog

## [0.4.0] - 2026-02-27
### Added
- Real Ed25519 crypto via PyNaCl (libsodium) — three-tier priority chain: saoe-core > PyNaCl > fail-closed
- Pluggable agent executors via `typing.Protocol` (`AgentExecutor`, `ToolGate`, `AllowlistToolGate`)
- SQLite-backed persistent transport queue (crash-safe, bounded, FIFO)
- Local envelope serialization (`to_local`/`from_local`) without saoe-core dependency
- Marketplace Ed25519 signature verification with configurable trust root key
- Architecture documentation (`docs/architecture.md`)
- API reference documentation (`docs/api-reference.md`)
- Quickstart guide (`docs/quickstart.md`)
- CLAUDE.md project identity file
- 149 new tests across 13 test files (unit + edge-case coverage)

### Changed
- Crypto bridge now produces real Ed25519 signatures (was HMAC stubs)
- `verify_data()` now returns `True` for valid signatures (was always `False`)
- `ThingsteadFleet` accepts `executor_factory` and `tool_gate` parameters
- `Transport` accepts `queue_db_path` for persistent queue mode
- `Marketplace.__init__` accepts `verification_public_key` parameter
- Hardening log updated with entries 12-15

### Removed
- `_fallback_sign()` HMAC stub (replaced by real PyNaCl signing)

## [0.3.0] - 2026-02-27
### Added
- Production hardening: Docker, CI/CD, env-driven config, observability hooks
- Full DLC Marketplace (local-first + signed distribution)
- Multi-agent Streamlit UI dashboard with live Thingstead telemetry
- SAOE ToolGate + SATL enforcement on every action
- Production config via pydantic-settings (CORVUSFORGE_* env vars)

### Changed
- Orchestrator now enforces production config
- Build Monitor 2.0 embedded in Streamlit dashboard

### Fixed
- Deterministic replay with Thingstead memory snapshot

## [0.2.0] - 2026-02-27
### Added
- Thingstead fleet integration (Invariant 11)
- Persistent memory in .openclaw-data (Invariant 12)
- Signed DLC plugins via ToolGate + SATL (Invariant 13)
- Full Multi-Agent UI (Invariant 14)
- DLC Marketplace (Invariant 15)

## [0.1.0] - 2026-02-26
### Added
- Initial deterministic pipeline with SAOE integration
- 10-stage pipeline (s0 through s7, including s5.5 accessibility + s5.75 security gates)
- Append-only hash-chained Run Ledger (Invariant 7)
- Content-addressed immutable artifact store (Invariant 8)
- Prerequisite DAG with cascade blocking
- Waiver management system
- Version pinning with drift detection
- Rich terminal Build Monitor (projection over ledger)
- Typer CLI with 5 commands (new, demo, monitor, saoe-status, release)
- Bridge layer for saoe-mvp integration
- 10 Core Invariants enforced structurally
