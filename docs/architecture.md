# Corvusforge Architecture

**Version:** 0.4.0
**Last updated:** 2026-02-27

## System Overview

Corvusforge is a 10-stage pipeline orchestrator that enforces 16 core invariants across every run. The architecture is built around three design principles:

1. **Determinism** — Every pipeline run is replayable from its ledger entries.
2. **Auditability** — Every state transition is hash-chained and content-addressed.
3. **Contract-driven** — Only validated JSON envelopes move between nodes.

## Component Diagram

```
                    ┌──────────────────────────────────┐
                    │         Typer CLI (cli/)          │
                    │  new | demo | monitor | ui | ...  │
                    └────────────────┬─────────────────┘
                                     │
                    ┌────────────────▼─────────────────┐
                    │         Orchestrator              │
                    │     (core/orchestrator.py)        │
                    │  Wires subsystems, drives runs    │
                    └──┬────┬────┬────┬────┬───────────┘
                       │    │    │    │    │
          ┌────────────┘    │    │    │    └──────────────┐
          ▼                 ▼    │    ▼                   ▼
   ┌─────────────┐ ┌────────────┐│ ┌─────────────┐ ┌───────────┐
   │  RunLedger  │ │StageMachine││ │ArtifactStore│ │EnvelopeBus│
   │  (SQLite,   │ │ (state +   ││ │ (content-   │ │ (envelope │
   │  hash-chain)│ │  prereqs)  ││ │  addressed) │ │  routing) │
   └─────────────┘ └────────────┘│ └─────────────┘ └───────────┘
                                 │
                    ┌────────────▼─────────────────┐
                    │      WaiverManager           │
                    │  (signed bypass artifacts)   │
                    └──────────────────────────────┘

   ┌──────────────────────────────────────────────────────────┐
   │                     Bridge Layer                         │
   │  ┌──────────────┐ ┌───────────┐ ┌────────────────────┐  │
   │  │ CryptoBridge │ │ Transport │ │   SAOE Adapter     │  │
   │  │ Ed25519 sign │ │ SQLite Q  │ │  to/from SATLEnv   │  │
   │  │ + verify     │ │ or SAOE   │ │  + local serial    │  │
   │  └──────────────┘ └───────────┘ └────────────────────┘  │
   │  ┌──────────────┐                                       │
   │  │ AuditBridge  │                                       │
   │  │ Dual-write   │                                       │
   │  └──────────────┘                                       │
   └──────────────────────────────────────────────────────────┘

   ┌──────────────────────────────────────────────────────────┐
   │                   Thingstead Fleet                       │
   │  ┌──────────────┐ ┌───────────┐ ┌────────────────────┐  │
   │  │ Fleet Mgmt   │ │ Executors │ │  Persistent Memory │  │
   │  │ spawn/status │ │ Protocol  │ │  .openclaw-data/   │  │
   │  │ + shutdown   │ │ pluggable │ │  shards + index    │  │
   │  └──────────────┘ └───────────┘ └────────────────────┘  │
   └──────────────────────────────────────────────────────────┘

   ┌──────────────────────────────────────────────────────────┐
   │              Plugin & Marketplace Layer                  │
   │  ┌──────────────┐ ┌───────────┐ ┌────────────────────┐  │
   │  │PluginLoader  │ │ Registry  │ │   Marketplace      │  │
   │  │ DLC packages │ │ entries   │ │  publish/verify/   │  │
   │  │ + manifest   │ │ + verify  │ │  install/search    │  │
   │  └──────────────┘ └───────────┘ └────────────────────┘  │
   └──────────────────────────────────────────────────────────┘
```

## Data Flow

### Pipeline Run Lifecycle

```
1. CLI invokes Orchestrator.start_run()
2. ProductionGuard checks environment constraints + trust root keys
3. Orchestrator initializes StageMachine (all stages → NOT_STARTED)
4. Orchestrator records intake (s0) transition in RunLedger
5. For each stage s1..s7:
   a. StageMachine checks prerequisites via PrerequisiteGraph
   b. Transition to RUNNING recorded in ledger (with trust_context)
   c. Stage handler executes (or ThingsteadFleet delegates to agent)
   d. Input/output hashes computed
   e. Transition to PASSED/FAILED recorded in ledger
   f. If FAILED: cascade-block dependents via PrerequisiteGraph
6. BuildMonitor projects ledger state for UI/terminal display
```

### Envelope Transport Flow

```
EnvelopeBase subclass (frozen Pydantic)
  → canonical_json_bytes() (deterministic serialization)
  → sha256_hex() (content address)
  → Transport.send() (SQLite queue or SAOE AgentShim)
  → Transport.receive() (atomic dequeue)
  → EnvelopeBus.receive() (parse + validate)
  → Dispatched to handlers via EnvelopeKind discriminator
```

## State Machine

### Stage States

```
NOT_STARTED ──→ RUNNING ──→ PASSED
     │              │           │
     │              └──→ FAILED │
     │                     │    │
     └──→ BLOCKED ◄────────┘    │
              │                 │
              └─── (retry) ────┘
```

Valid transitions (enforced by `StageMachine`):

| From | To |
|------|----|
| NOT_STARTED | RUNNING |
| RUNNING | PASSED |
| RUNNING | FAILED |
| NOT_STARTED | BLOCKED (cascade) |
| BLOCKED | NOT_STARTED (unblock) |
| FAILED | RUNNING (retry) |

### Pipeline Stages

| ID | Name | Prerequisites |
|----|------|---------------|
| s0 | Intake | None |
| s1 | Prerequisites Synthesis | s0 |
| s2 | Environment Readiness | s1 |
| s3 | Test Contracting | s2 |
| s4 | Code Plan | s3 |
| s5 | Implementation | s4 |
| s55 | Accessibility Gate | s5 |
| s575 | Security Gate | s55 |
| s6 | Verification | s575 |
| s7 | Release and Attestation | s6 |

## Hash Chain Structure

Every `LedgerEntry` includes:

```
entry_hash = SHA-256(
    entry_id + run_id + stage_id + state_transition +
    timestamp_utc + input_hash + output_hash +
    artifact_refs + pipeline_version + schema_version +
    toolchain_version + ruleset_versions + waiver_refs +
    trust_context + trust_context_version + payload_hash +
    previous_entry_hash
)
```

The `previous_entry_hash` links each entry to its predecessor, forming an append-only chain within each `run_id`. The SQLite UNIQUE constraint on `entry_hash` provides an additional defense-in-depth layer against hash-swap attacks.

### External Anchoring

`RunLedger.export_anchor()` produces a signed digest (run_id, entry_count, root_hash, first_entry_hash) for posting to external transparency systems. `verify_against_anchor()` detects retroactive chain rewrites by comparing against a previously-exported anchor.

## Trust Boundaries

### Three-Tier Crypto Priority

```
Tier 1: saoe-core Keyring     (full SATL-compatible Ed25519)
Tier 2: PyNaCl (libsodium)    (native Ed25519 via nacl.signing)
Tier 3: Fail-closed           (verify_data() always returns False)
```

The crypto bridge selects the highest-available tier at import time. There is no fallback to "permissive" — if crypto is unavailable, verification fails.

### Trust Context

Every ledger entry records key fingerprints (16-hex-char SHA-256 prefix) of the active trust roots:

- `plugin_trust_root_fp` — public key for DLC plugin verification
- `waiver_signing_key_fp` — public key for waiver signature checks
- `anchor_key_fp` — public key for anchor export signing

Key rotation is detectable by comparing fingerprints across consecutive ledger entries.

### Production Guard

Before any pipeline execution, `enforce_production_constraints()` validates:

1. Environment mode (debug vs production)
2. All required trust keys have non-empty values
3. Waiver signature enforcement is active in production

Failure is hard — the pipeline will not start with an incomplete trust configuration.

## Fleet Architecture

### ThingsteadFleet

```
ThingsteadFleet
  ├── FleetConfig (frozen: name, max_agents, data_dir, signing)
  ├── AgentState[] (agent_id, role, stage_id, status, timing)
  ├── FleetMemory
  │     ├── MemoryShard[] (content-hashed, run-scoped, integrity-verified)
  │     └── Index (persisted to .openclaw-data/)
  └── FleetEvent[] (observability log)
```

### Pluggable Executor Protocol

```python
class AgentExecutor(Protocol):
    def execute(self, payload: dict) -> dict: ...

class ToolGate(Protocol):
    def check(self, tool_name: str) -> bool: ...
```

Priority chain: saoe-core AgentShim → user-provided factory → DefaultExecutor.

## Routing Architecture

### SinkDispatcher

The `SinkDispatcher` fans out envelopes to all registered `BaseSink` implementations. Partial failure is tolerated (individual sink errors are collected); total failure raises `SinkDispatchError`.

Built-in sinks:
- `LocalFileSink` — writes envelope JSON to disk, organized by run_id/stage_id

## Module Map

| Directory | Purpose |
|-----------|---------|
| `bridge/` | Adapters: crypto, audit, transport, SAOE |
| `cli/` | Typer CLI entry points |
| `contrib/` | User contribution hooks + decision registry |
| `core/` | Orchestrator, RunLedger, StageMachine, ArtifactStore |
| `dashboard/` | Streamlit Build Monitor 2.0 |
| `marketplace/` | Local-first DLC marketplace |
| `models/` | Pydantic models (frozen, validated) |
| `monitor/` | Projection + Rich terminal renderer |
| `plugins/` | DLC plugin loader + registry |
| `routing/` | SinkDispatcher + sink backends |
| `stages/` | BaseStage + 10 concrete stages |
| `thingstead/` | Fleet management, executors, persistent memory |
