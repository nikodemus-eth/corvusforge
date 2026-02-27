# Corvusforge API Reference

**Version:** 0.4.0
**Last updated:** 2026-02-27

## Core

### Orchestrator

`corvusforge.core.orchestrator.Orchestrator`

Central pipeline coordinator. Wires together all subsystems and drives pipeline runs.

```python
from corvusforge.core.orchestrator import Orchestrator

orch = Orchestrator(config=PipelineConfig(), prod_config=ProdConfig())
run_config = orch.start_run(prerequisites=[...])
result = orch.execute_stage("s1_prerequisites", payload={...})
states = orch.get_states()
entries = orch.get_run_entries()
valid = orch.verify_chain()
```

**Constructor:**
- `config: PipelineConfig | None` — Pipeline settings (ledger path, artifact path, version pin).
- `run_id: str | None` — Resume an existing run. Auto-generated if `None`.
- `prod_config: ProdConfig | None` — Production environment configuration.

**Methods:**
- `start_run(prerequisites=None) -> RunConfig` — Initialize a new pipeline run.
- `resume_run(run_id) -> dict[str, StageState]` — Resume from ledger state.
- `register_stage_handler(stage_id, handler)` — Register a callable for a stage.
- `execute_stage(stage_id, payload=None) -> dict` — Run a stage through its handler.
- `get_states() -> dict[str, StageState]` — Current state of all stages.
- `get_stage_state(stage_id) -> StageState` — Current state of one stage.
- `get_run_entries() -> list[LedgerEntry]` — All ledger entries for the run.
- `verify_chain() -> bool` — Verify hash chain integrity.

---

### RunLedger

`corvusforge.core.run_ledger.RunLedger`

Append-only, hash-chained ledger backed by SQLite (Invariant 7).

```python
from corvusforge.core.run_ledger import RunLedger

ledger = RunLedger(db_path=Path("ledger.db"))
sealed = ledger.append(entry)
entries = ledger.get_run_entries("run-001")
ledger.verify_chain("run-001")
anchor = ledger.export_anchor("run-001")
ledger.verify_against_anchor("run-001", anchor)
```

**Methods:**
- `append(entry: LedgerEntry) -> LedgerEntry` — Append and seal with hash chain. **Only write method.**
- `get_latest(run_id) -> LedgerEntry | None` — Most recent entry.
- `get_stage_history(run_id, stage_id) -> list[LedgerEntry]` — History for one stage.
- `get_run_entries(run_id) -> list[LedgerEntry]` — All entries for a run.
- `get_all_run_ids() -> list[str]` — All distinct run IDs.
- `verify_chain(run_id) -> bool` — Recompute and verify hashes. Raises `LedgerIntegrityError`.
- `export_anchor(run_id) -> dict` — Export tamper-evident anchor for external witnessing.
- `verify_against_anchor(run_id, anchor) -> bool` — Verify chain against exported anchor.

---

### StageMachine

`corvusforge.core.stage_machine.StageMachine`

Enforces valid state transitions and prerequisite checks (Invariants 4, 5, 6).

```python
from corvusforge.core.stage_machine import StageMachine

sm = StageMachine(ledger=ledger, graph=prereq_graph)
sm.initialize_run("run-001")
entry = sm.transition("run-001", "s0_intake", StageState.RUNNING)
can, reasons = sm.can_start("run-001", "s1_prerequisites")
```

**Methods:**
- `initialize_run(run_id) -> dict[str, StageState]` — Set all stages to NOT_STARTED.
- `transition(run_id, stage_id, target_state, ...) -> LedgerEntry` — Transition with validation.
- `get_current_state(run_id, stage_id) -> StageState` — Current state.
- `get_all_states(run_id) -> dict[str, StageState]` — All stage states.
- `can_start(run_id, stage_id) -> tuple[bool, list[str]]` — Check if stage can start.
- `get_available_transitions(run_id, stage_id) -> set[StageState]` — Valid target states.

---

## Bridge Layer

### CryptoBridge

`corvusforge.bridge.crypto_bridge`

Three-tier signing: saoe-core > PyNaCl (Ed25519) > fail-closed.

```python
from corvusforge.bridge.crypto_bridge import (
    generate_keypair, sign_data, verify_data,
    hash_pin, key_fingerprint, compute_trust_context,
    is_saoe_crypto_available, is_native_crypto_available,
)

priv, pub = generate_keypair()
sig = sign_data(b"payload", priv)
valid = verify_data(b"payload", sig, pub)  # True
fp = key_fingerprint(pub)                  # 16-char hex prefix
ctx = compute_trust_context(plugin_trust_root=pub)
```

**Functions:**
- `generate_keypair() -> tuple[str, str]` — `(private_hex, public_hex)`.
- `sign_data(data: bytes, private_key: str) -> str` — Hex-encoded Ed25519 signature.
- `verify_data(data: bytes, signature: str, public_key: str) -> bool` — **Fail-closed**: returns `False` unless proof succeeds.
- `hash_pin(pin: str, salt=None) -> str` — Salted SHA-256 hash (`"salt_hex:digest_hex"`).
- `key_fingerprint(public_key: str) -> str` — First 16 hex chars of SHA-256.
- `compute_trust_context(...) -> dict[str, str]` — Build fingerprint dict for ledger entries.
- `is_saoe_crypto_available() -> bool` — saoe-core backend loaded?
- `is_native_crypto_available() -> bool` — PyNaCl backend loaded?

---

### Transport

`corvusforge.bridge.transport.Transport`

Unified send/receive for Corvusforge envelopes. SQLite queue (persistent) or in-memory deque (volatile).

```python
from corvusforge.bridge.transport import Transport

# Persistent queue
t = Transport(agent_id="node-1", queue_db_path=Path("queue.db"))
t.send(envelope)
raw = t.receive()
messages = t.drain(max_messages=50)
t.close()

# Context manager
with Transport(queue_db_path=Path("q.db")) as t:
    t.send(envelope)
```

**Constructor:**
- `agent_id: str` — Node identifier.
- `channel: str` — Logical channel name.
- `max_local_queue: int` — Bounded queue depth (default 1024).
- `queue_db_path: Path | None` — SQLite path. `None` = in-memory deque.

**Methods:**
- `send(envelope) -> str` — Serialize and enqueue. Returns `envelope_id`.
- `receive(timeout_seconds=0.0) -> bytes | None` — Dequeue oldest message.
- `drain(max_messages=100) -> list[bytes]` — Drain up to N messages.
- `close()` — Release resources.

**Properties:**
- `is_networked: bool` — True if backed by SAOE AgentShim.
- `local_queue_depth: int` — Messages waiting.

---

### SAOE Adapter

`corvusforge.bridge.saoe_adapter`

Converts between Corvusforge envelopes and SAOE SATLEnvelopes. Local serialization path available without saoe-core.

```python
from corvusforge.bridge.saoe_adapter import to_local, from_local

data = to_local(envelope, signing_key=priv)
reconstructed = from_local(data)
```

**Functions:**
- `to_satl(envelope, signing_key, template_ref) -> SATLEnvelope` — Requires saoe-core.
- `from_satl(satl_envelope) -> EnvelopeBase` — Requires saoe-core.
- `to_local(envelope, signing_key) -> dict` — Ed25519-signed local serialization.
- `from_local(data: dict) -> EnvelopeBase` — Reconstitute from local dict.
- `is_saoe_satl_available() -> bool` — SATL module loaded?

---

### AuditBridge

`corvusforge.bridge.audit_bridge`

Dual-write: RunLedger + saoe-core AuditLog (when available).

**Functions:**
- `record_transition(entry, ledger, saoe_audit_log=None) -> LedgerEntry` — Append to ledger.
- `record_envelope_event(envelope, event_type, ledger=None) -> LedgerEntry | None` — Log envelope events.
- `is_saoe_audit_available() -> bool` — saoe-core audit loaded?

---

## Thingstead Fleet

### ThingsteadFleet

`corvusforge.thingstead.fleet.ThingsteadFleet`

Manages agent pools for pipeline execution (Invariant 11).

```python
from corvusforge.thingstead.fleet import ThingsteadFleet, FleetConfig

fleet = ThingsteadFleet(
    config=FleetConfig(fleet_name="prod", max_agents=4),
    tool_gate=AllowlistToolGate(["read_file", "write_file"]),
)
result = fleet.execute_stage("s5_implementation", payload={...})
status = fleet.get_fleet_status()
fleet.shutdown()
```

**Constructor:**
- `config: FleetConfig | None` — Fleet settings.
- `orchestrator: Orchestrator | None` — Optional orchestrator reference.
- `executor_factory` — Custom `(agent_id, role) -> AgentExecutor` factory.
- `tool_gate: ToolGate | None` — Custom tool gate. Default allows all.

**Methods:**
- `spawn_agent(role, stage_id) -> str` — Create agent. Returns `agent_id`.
- `execute_stage(stage_id, payload=None) -> dict` — Full execution cycle.
- `get_fleet_status() -> dict` — Fleet summary.
- `shutdown()` — Persist memory, mark agents completed.

---

### Executor Protocol

`corvusforge.thingstead.executors`

```python
from corvusforge.thingstead.executors import (
    AgentExecutor, ToolGate,          # Protocols
    DefaultExecutor, DefaultToolGate,  # Defaults
    AllowlistToolGate,                 # Restrictive gate
)
```

- `AgentExecutor` — Protocol: `execute(payload: dict) -> dict`
- `ToolGate` — Protocol: `check(tool_name: str) -> bool`
- `DefaultExecutor` — Pass-through (returns payload with status).
- `DefaultToolGate` — Allows all tools.
- `AllowlistToolGate` — Blocks tools not in configured allowlist.

---

## Plugin System

### PluginLoader

`corvusforge.plugins.loader.PluginLoader`

Reads, verifies, and installs DLC plugin packages.

**Methods:**
- `install_dlc(package_dir) -> PluginEntry` — Install a DLC package from disk.
- `verify_plugin(name) -> bool` — Verify plugin signature.

### Marketplace

`corvusforge.marketplace.marketplace.Marketplace`

Local-first DLC marketplace for publishing and installing signed plugins.

```python
from corvusforge.marketplace.marketplace import Marketplace

mp = Marketplace(
    marketplace_dir=Path(".corvusforge/marketplace/"),
    verification_public_key=pub_key,
)
listing = mp.publish(package_path, author="CORVUSFORGE, LLC")
verified = mp.verify_listing("plugin-name")
entry = mp.install("plugin-name")
results = mp.search(query="slack", kind=PluginKind.SINK)
stats = mp.get_stats()
```

**Methods:**
- `publish(package_path, author, tags=None) -> MarketplaceListing` — Publish to local catalog.
- `install(name) -> PluginEntry` — Install from marketplace.
- `search(query="", kind=None, tags=None) -> list[MarketplaceListing]` — Search catalog.
- `verify_listing(name) -> bool` — Ed25519 signature verification. **Fail-closed.**
- `get_listing(name) -> MarketplaceListing | None` — Get single listing.
- `list_all() -> list[MarketplaceListing]` — All listings.
- `get_stats() -> dict` — Summary statistics.

---

## Envelope Types

`corvusforge.models.envelopes`

All envelopes are frozen Pydantic models. Six contracted types:

| Type | Purpose | Key Fields |
|------|---------|------------|
| `WorkOrderEnvelope` | Instructs work on a stage | `stage_id`, `work_specification` |
| `EventEnvelope` | Reports state transitions | `event_type`, `stage_id`, `details` |
| `ArtifactEnvelope` | References content-addressed artifacts | `artifact_ref`, `artifact_type` |
| `ClarificationEnvelope` | Requests operator input | `question`, `blocking_stage_id` |
| `FailureEnvelope` | Reports stage failures | `error_code`, `error_message`, `recoverable` |
| `ResponseEnvelope` | Responds to clarifications | `in_reply_to`, `response_payload` |

**Common base fields** (`EnvelopeBase`): `envelope_id`, `run_id`, `source_node_id`, `destination_node_id`, `envelope_kind`, `payload_hash`, `timestamp_utc`, `schema_version`.

---

## Routing

### SinkDispatcher

`corvusforge.routing.dispatcher.SinkDispatcher`

Fans out envelopes to all registered sinks. Partial failure tolerant.

**Methods:**
- `register(name, sink)` — Register a `BaseSink`.
- `unregister(name)` — Remove a sink.
- `dispatch(envelope) -> dict[str, bool]` — Send to all sinks. Returns success map.
- `batch_dispatch(envelopes) -> list[dict[str, bool]]` — Dispatch multiple.

### BaseSink Protocol

```python
class BaseSink(Protocol):
    def write(self, envelope: EnvelopeBase) -> None: ...
```

Built-in: `LocalFileSink` — writes JSON to `{base_dir}/{run_id}/{stage_id}/{envelope_id}.json`.

---

## Monitor

### BuildMonitor (MonitorProjection)

`corvusforge.monitor.projection.MonitorProjection`

Projects RunLedger state into a displayable snapshot.

**Methods:**
- `snapshot(run_id) -> MonitorSnapshot` — Build current snapshot.

### MonitorRenderer

`corvusforge.monitor.renderer.MonitorRenderer`

Rich terminal display of pipeline state.

**Methods:**
- `render_snapshot(snapshot) -> Panel` — Render a Rich Panel.
- `print_chain_verification(run_id, ledger)` — Print chain status.
