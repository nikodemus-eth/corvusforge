# Corvusforge Threat Model

**Version:** 1.0
**Date:** 2026-02-26
**Scope:** Core pipeline (ledger, stages, artifacts, waivers, plugins, routing, memory shards)

---

## 1. System Overview

Corvusforge is a deterministic, auditable, contract-driven coding pipeline. It enforces a fixed stage sequence (s0-s7 plus mandatory gates) with hash-chained ledger entries, content-addressed artifact storage, cryptographic plugin verification, and waiver-controlled gate bypass.

The system is single-tenant, single-writer. There is no multi-user access control layer. The threat model assumes a single operator who may be compromised or whose environment may be compromised.

---

## 2. Attacker Tiers

### Tier 0: Casual Misuse (Insider, Non-Malicious)

**Capabilities:** Can run CLI commands, create waivers, register plugins, execute pipeline stages. Has no intent to subvert invariants but may cut corners.

**Examples:**
- Creating unsigned waivers to skip accessibility gates during a deadline.
- Registering an unverified plugin to test locally.
- Skipping the security scan stage by manipulating stage state.

**Mitigations:**
- Strict waiver mode in production (ADR-0002) prevents unsigned gate bypass.
- Stage machine enforces prerequisite ordering — cannot skip to s7 without passing gates.
- Ledger records all transitions — casual bypass leaves an audit trail.

### Tier 1: Local File Write (Compromised Dev Environment)

**Capabilities:** Can read and write any file in the project directory, including the SQLite ledger, artifact store, plugin registry, and configuration files. Cannot modify the Corvusforge source code itself (or if they can, all bets are off).

**Examples:**
- Directly modifying SQLite ledger entries to fake stage completion.
- Replacing an artifact file with different content (same filename).
- Editing the plugin registry JSON to mark an unverified plugin as verified.
- Deleting ledger entries to hide a failed stage.

**Mitigations:**
- Hash chain in ledger detects any entry modification (`verify_chain()`).
- External anchoring (ADR-0003) detects full chain rewrites by comparing against out-of-band witness.
- Content-addressed artifacts are keyed by SHA-256 of content — replacing content changes the key, breaking all references.
- SQLite UNIQUE constraint on `entry_hash` prevents hash-swap attacks at the DB level.
- Plugin verified flag is set by crypto verification, not by file content — editing the JSON flag doesn't change what `verify_plugin()` returns on next call.

**Residual risk:** If anchors are stored in the same filesystem, a Tier 1 attacker can rewrite both ledger and anchor. Operational guidance: store anchors outside the local trust domain.

### Tier 2: Plugin Supply Chain (Malicious Plugin Author)

**Capabilities:** Can create and distribute a plugin package. Can control the plugin's code, manifest, and (if self-attested) its own signing key. Cannot modify the Corvusforge runtime or other plugins.

**Examples:**
- Publishing a plugin with a valid self-attested signature but malicious code.
- Publishing a plugin that passes verification but contains a backdoor in its stage hook.
- Publishing a plugin that exploits the loader to execute code during installation.

**Mitigations:**
- Fail-closed verification (ADR-0001) ensures unverifiable plugins are never marked verified.
- Plugin verification checks signature but does not sandbox execution — this is a known gap.
- Plugin kind restrictions (`PluginKind` enum) limit where plugins can hook into the pipeline.
- All plugin registrations are recorded in the plugin registry JSON with verification status.

**Residual risk:** Self-attestation means the plugin author controls both payload and verification key. A future trust root (e.g., a curated key registry) is needed to close this gap. Plugin code execution is not sandboxed — a malicious plugin can do anything the Python process can do.

### Tier 3: CI/CD Pipeline Compromise

**Capabilities:** Can execute arbitrary commands in the CI environment. Can read environment variables, access secrets, modify files, and push to the repository. May have access to signing keys stored as CI secrets.

**Examples:**
- Extracting signing keys from CI secrets and signing forged waivers.
- Modifying the ledger database before anchor export, then exporting a "clean" anchor.
- Replacing the Corvusforge binary with a modified version that skips verification.
- Pushing a commit that modifies `registry.py` to re-introduce fail-open verification.

**Mitigations:**
- External anchors stored outside CI (e.g., separate S3 bucket with different credentials) survive CI compromise.
- Code review catches source code modifications (Corvusforge's own code is not self-modifying).
- If signing keys are compromised, key rotation procedures (see runbook) limit the blast radius.

**Residual risk:** A compromised CI pipeline with access to signing keys can forge any artifact. This is the highest-impact scenario. Mitigation requires key management practices (HSM, short-lived keys, multi-party signing) that are outside Corvusforge's current scope.

---

## 3. Trust Roots

| Trust Root | What It Protects | Storage | Rotation | CI Access |
|-----------|-----------------|---------|----------|-----------|
| Plugin signing keys | Plugin identity and integrity | CI secrets manager | Per-key, revoke via registry | **Yes** — CI signs plugins (see ADR-0007) |
| Waiver signing keys | Gate bypass authorization | Human approver's local keystore | Per-approver, revoke by expiration | **No** — offline only (see ADR-0007) |
| Anchor export key | Ledger authenticity witness | CI secrets manager | Per-key | **Yes** — CI exports anchors |
| Anchor witness location | Ledger authenticity (storage) | External to project — **must be outside ledger write domain** | N/A (append-only) | Separate credentials required |
| SHA-256 hash function | All content addressing, all chain integrity | Algorithm — no key | N/A (algorithm replacement = major version) | N/A |

### Key Fingerprint Recording

Every ledger entry records a `trust_context` dict containing fingerprints of the signing keys active at entry creation time:

- `plugin_trust_root_fp`: SHA-256 prefix of the plugin verification public key
- `waiver_signing_key_fp`: SHA-256 prefix of the waiver verification public key
- `anchor_key_fp`: SHA-256 prefix of the anchor signing public key

Fingerprints are sealed into the entry hash. Changing a fingerprint after the fact breaks the hash chain. This enables forensic identification of which trust root was active for any given ledger entry, and makes key rotation boundaries visible.

### Trust Assumptions

1. **SHA-256 is collision-resistant.** All content addressing, hash chaining, and integrity verification depends on this. If SHA-256 is broken, the entire integrity model fails.
2. **Ed25519 signatures are unforgeable without the private key.** Plugin and waiver verification depends on this.
3. **The Corvusforge source code is unmodified.** The system does not verify its own integrity. A modified binary can bypass all checks.
4. **The Python runtime is unmodified.** A compromised Python interpreter can bypass any Python-level check.
5. **CI is inside the TCB for plugin signing and anchor export.** A compromised CI can forge plugins and anchors. CI is explicitly **not** trusted for waiver signing (see ADR-0007).

---

## 4. Trusted Computing Base (TCB)

The TCB is the minimal set of components that must be correct for the security properties to hold.

### Inside the TCB

| Component | Why |
|-----------|-----|
| `run_ledger.py` | Hash chain computation and verification |
| `artifact_store.py` | Content addressing (SHA-256 keying) |
| `hasher.py` | All hash computations (`sha256_hex`, `canonical_json_bytes`) |
| `crypto_bridge.py` | Ed25519 signature verification, key fingerprinting, trust context |
| `waiver_manager.py` | Waiver signature enforcement |
| `stage_machine.py` | Stage transition enforcement and prerequisite checking |
| `prerequisite_graph.py` | Stage dependency definitions |
| `envelope_bus.py` | Envelope validation (type checking, schema enforcement) |
| `production_guard.py` | Production constraint enforcement at startup |
| CI/CD pipeline | Plugin signing, anchor export (see ADR-0007) |
| Python runtime | Execution environment |
| SQLite | Ledger storage (UNIQUE constraints, WAL) |
| Operating system | File I/O, process isolation |

### Outside the TCB

| Component | Why |
|-----------|-----|
| `monitor/` | Read-only projection, cannot modify ledger |
| `dashboard/` | UI layer, no security decisions |
| `cli/` | User interface, delegates to core |
| `routing/sinks/` | Event delivery, no integrity decisions |
| `stages/` | Stage handler implementations, sandboxed by stage machine |
| `contrib/` | Extension points, no core invariant enforcement |
| `marketplace/` | Plugin discovery, not trust enforcement |

---

## 5. Failure Behaviors by Trust Boundary

| Boundary | Failure Mode | Required Behavior |
|----------|-------------|-------------------|
| Plugin verification | Crypto unavailable | Return `unverified` (ADR-0001) |
| Plugin verification | Exception during verify | Return `unverified` (ADR-0001) |
| Waiver registration (strict) | No signature | Raise `WaiverSignatureError` (ADR-0002) |
| Waiver registration (strict) | Invalid signature | Raise `WaiverSignatureError` (ADR-0002) |
| Waiver registration (permissive) | No signature | Register with `signature_verified=False` |
| Ledger write | Hash computation failure | Abort entry (do not write partial) |
| Ledger verify | Chain broken | Raise `LedgerIntegrityError` |
| Anchor verify | Truncation detected | Raise `LedgerIntegrityError` |
| Anchor verify | Rewrite detected | Raise `LedgerIntegrityError` |
| Stage transition | Prerequisites not met | Raise `PrerequisiteError` |
| Stage transition | Invalid state change | Raise `InvalidTransitionError` |
| Envelope receive | Non-dict JSON | Raise `EnvelopeValidationError` |
| Envelope receive | Unknown kind | Raise `EnvelopeValidationError` |
| Shard verification | Content hash mismatch | Raise `ShardIntegrityError` |
| Sink dispatch | Single sink failure | Log warning, continue to other sinks (ADR-0006) |
| Sink dispatch | All sinks fail | Raise `SinkDispatchError` |

---

## 6. Open Risks and Future Work

1. **Plugin self-attestation.** Plugins supply their own public key. A curated trust root or key registry is needed.
2. **No code execution sandbox for plugins.** A malicious plugin can execute arbitrary code.
3. **No runtime integrity verification.** Corvusforge does not verify its own binaries or the Python runtime.
4. **Single-writer assumption.** Multi-user access control is not modeled. If multiple users share a Corvusforge instance, there is no isolation between their operations.
5. **Signing key management.** No HSM integration, no short-lived key support, no multi-party signing. CI signing keys should migrate to HSM or short-lived keys as the deployment matures.
6. **Anchor storage is operational, not enforced.** The system exports anchors but does not enforce where they are stored or that they are stored at all. Anchors stored alongside the repo provide zero additional security over the hash chain alone.
7. **CI compromise scope.** Per ADR-0007, CI is inside the TCB for plugin signing and anchor export. A compromised CI can forge plugins and anchors. Waiver signing is excluded from CI, which limits blast radius. Future work: offline-only signing or HSM-backed CI signing.
8. **Key loss recovery.** If an anchor key is lost, existing anchors remain valid (they're just data), but new anchors cannot be verified against the same trust root. The fingerprint trail in the ledger allows forensic identification of the affected window. A key loss does not invalidate the hash chain — only the external anchor verification.
