# Corvusforge v0.4.0 Release Notes

**Release date:** 2026-02-27
**License:** AGPL-3.0-only
**Test count:** 387 (up from 238 in v0.3.0)

## Headline

Corvusforge v0.4.0 replaces stub implementations with real cryptography, pluggable executor backends, and persistent transport — making the system fully functional without the unpublished saoe-core dependency.

## Key Changes

### Real Ed25519 Cryptography (Phase 1)

The crypto bridge now uses PyNaCl (libsodium) for real Ed25519 signing and verification. The three-tier priority chain ensures the strongest available backend is always used:

1. **saoe-core Keyring** (when installed) — full SATL-compatible signing
2. **PyNaCl** (new in v0.4.0) — native Ed25519 via libsodium
3. **Fail-closed** — `verify_data()` returns `False`, system refuses to trust

This unlocks real signature verification across the entire pipeline: plugins, marketplace listings, waivers, and SAOE adapters.

### Pluggable Agent Executors (Phase 2)

`ThingsteadFleet` now supports Protocol-based executor and tool gate backends:

- `AgentExecutor` — structural typing via `typing.Protocol`
- `ToolGate` — `check(tool_name) -> bool` interface
- `AllowlistToolGate` — restricts agents to a configured set of tools
- Priority: saoe-core > user-provided factory > DefaultExecutor

### SQLite-Backed Transport Queue (Phase 3)

The `Transport` class now supports persistent message queuing via SQLite:

- `queue_db_path` parameter enables persistent mode
- AUTOINCREMENT primary key guarantees FIFO ordering
- Atomic SELECT + DELETE for crash-safe dequeue
- Bounded at `max_local_queue` depth (default 1024)
- Context manager support for clean resource lifecycle

### Local Envelope Serialization (Phase 4)

New `to_local()` and `from_local()` functions in the SAOE adapter provide Ed25519-signed envelope serialization without requiring saoe-core. Useful for local storage and offline verification.

### Marketplace Real Verification (Phase 5)

`Marketplace.verify_listing()` now performs real Ed25519 signature verification using the PyNaCl crypto bridge. A `verification_public_key` must be configured at construction time. Fail-closed: missing key, empty signature, or unavailable crypto all result in `False`.

### Edge-Case Test Coverage (Phase 6)

74 new tests across 7 test files filling coverage gaps in:
- Audit bridge (dual-write, saoe-unavailable paths)
- CLI commands (all 7 registered commands)
- Stage lifecycle (base stage enforcement, prerequisites, waivers)
- Routing (dispatcher fan-out, partial failure, LocalFileSink I/O)
- Contrib (hooks, decision registry, replay maps)
- Orchestrator (construction, start_run, handler registration)
- Monitor renderer (Rich output, trust context display)

## Breaking Changes

None. All changes are backward compatible. Existing code that doesn't pass `verification_public_key`, `queue_db_path`, `executor_factory`, or `tool_gate` gets the same behavior as v0.3.0.

## Dependencies

Added to core dependencies:
- `PyNaCl>=1.5.0` (Ed25519 via libsodium)

## Upgrade Path

```bash
pip install --upgrade corvusforge==0.4.0
```

No migration steps required. Existing ledger databases, artifact stores, and fleet memory are fully compatible.

## Verification

```bash
# Confirm version
python -c "import corvusforge; print(corvusforge.__version__)"
# Expected: 0.4.0

# Confirm real crypto
python -c "
from corvusforge.bridge.crypto_bridge import *
priv, pub = generate_keypair()
sig = sign_data(b'v0.4.0', priv)
print('Ed25519 OK:', verify_data(b'v0.4.0', sig, pub))
"
# Expected: Ed25519 OK: True

# Run tests
pytest --tb=short -q
# Expected: 387 passed
```
