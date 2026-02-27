# Corvusforge Hardening Log

**Started:** 2026-02-26
**Directive:** Do not grow. Compress. Stabilize.
**Scope:** Phase 1 Hardening — close structural gaps in security, integrity, and reproducibility.

---

## Risk Surface Audit (2026-02-26)

### Methodology
Read every core module against the 16 invariants. Identified five risk areas, categorized into two tiers.

### Findings

#### Critical — Active Vulnerabilities

| # | Risk | Location | Impact |
|---|------|----------|--------|
| C1 | Plugin auto-verify on exception | `registry.py:267-310`, `loader.py:258-292` | Unsigned plugins marked `verified=True` when crypto fails or throws. Self-attestation: plugin supplies its own public key. |
| C2 | Waiver signature never checked | `waiver_manager.py:38-62`, `waivers.py:42` | `signature` field defaults to `""` and is never verified. Any caller can forge a waiver bypassing mandatory gates. |

#### Important — Integrity & Reproducibility Gaps

| # | Risk | Location | Impact |
|---|------|----------|--------|
| I1 | No external ledger anchoring | `run_ledger.py` (entire module) | Hash chain proves internal consistency but not independent verifiability. Adversary with SQLite write access can recompute entire chain. |
| I2 | Memory shards not run-scoped | `memory.py:34-73` | `MemoryShard` has no `run_id` field. Shards accumulate across runs. No per-run snapshot. No integrity re-verification on read. |
| I3 | Tests assert functionality, not invariant violations | `tests/unit/`, `tests/integration/` | 135 tests confirm correct behavior. None test tamper detection, invalid envelope rejection, prerequisite bypass, or expired-waiver edge cases. |
| I4 | Routing profiles not fuzz-tested | `routing/dispatcher.py` | Sink failure isolation is coded but never adversarially tested. No test for malformed envelopes, sink exceptions during batch dispatch, or all-sinks-fail scenario. |

---

## Implementation Journal

### Entry 1 — Critical Fix C1: Plugin Auto-Verify Elimination
**Date:** 2026-02-26
**Problem:** `verify_plugin()` and `verify_dlc()` both catch `Exception` and set `verified=True` as fallback. This inverts the security model — failure-to-verify becomes implicit trust.
**Fix:** Default to `verified=False` on any error. Remove the `except Exception → verified=True` pattern. When crypto bridge is unavailable, log a warning and leave `verified=False` — never auto-promote.
**Rationale:** Invariant 13 says "Signed DLC plugins." A plugin that cannot be verified is not signed. Unverified != untrusted-but-allowed. Unverified == not-yet-trusted.
**Lesson:** Fail-open crypto is worse than no crypto. It creates false confidence.

### Entry 2 — Critical Fix C2: Waiver Signature Enforcement
**Date:** 2026-02-26
**Problem:** `WaiverManager.register_waiver()` stores waivers as content-addressed artifacts but never verifies the `signature` field against `approving_identity`. Anyone can construct a `WaiverArtifact` with arbitrary identity and it registers.
**Fix:** Add signature verification step in `register_waiver()`. If crypto bridge is available, verify signature over canonical waiver bytes against `approving_identity` public key. If signature is empty or invalid, raise `WaiverSignatureError`. If crypto bridge is unavailable, accept but mark waiver as `unverified` in metadata.
**Rationale:** Waivers bypass mandatory gates (Invariants 5, 6). They are the most security-critical artifact in the system. An unsigned waiver is a backdoor.
**Lesson:** The most sensitive operations need the strictest verification, not the loosest.

### Entry 3 — Important Fix I1: External Ledger Anchoring
**Date:** 2026-02-26
**Problem:** The hash chain is self-referential. Internal verification passes even on a fully-rewritten chain.
**Fix:** Add `export_anchor()` method that returns a signed `LedgerAnchor` (run_id, entry_count, root_hash, timestamp, signature). Anchors can be posted to external systems (file, transparency log, etc.) for independent verification. Add `verify_against_anchor()` method.
**Rationale:** Invariant 7 says "append-only." But append-only is only meaningful if the chain can be externally witnessed.

### Entry 4 — Important Fix I2: Memory Shard Run Isolation
**Date:** 2026-02-26
**Problem:** `MemoryShard` has no `run_id`. Shards from different runs intermingle. No integrity check on read.
**Fix:** Add `run_id` field to `MemoryShard`. Add `verify_shard()` method that re-hashes content and compares to `content_hash`. Add `snapshot_for_run()` that returns all shards for a given run with verified integrity.
**Rationale:** Invariant 10 says "replayable and resumable deterministically." Deterministic replay requires knowing exactly which memory state existed at a given run.

### Entry 5 — Important Fix I3: Adversarial Tests
**Date:** 2026-02-26
**Problem:** Tests are happy-path. They confirm the system works when used correctly. They don't confirm it fails when attacked.
**Fix:** Add `tests/adversarial/` directory with tests that corrupt ledger rows, send malformed envelopes, attempt prerequisite bypasses, register unsigned plugins, and create forged waivers.
**Rationale:** "What matters is what they assert." An invariant that isn't tested under violation is an invariant in name only.

### Entry 6 — Important Fix I4: Fuzz Routing Profiles
**Date:** 2026-02-26
**Problem:** `SinkDispatcher` handles failures gracefully in code, but this is never tested with adversarial inputs.
**Fix:** Add fuzz tests that: send envelopes with missing fields, register sinks that throw various exception types, test batch dispatch with mixed success/failure, verify the all-sinks-fail → `SinkDispatchError` path.
**Rationale:** Invariant 9 says "every event routes to all configured sinks." Routing resilience under failure is the invariant, not just routing under success.

---

### Entry 7 — Bug Found: Envelope Bus JSON Array Crash
**Date:** 2026-02-26
**Problem:** Adversarial test `test_reject_json_array` sent `b'[1, 2, 3]'` to `EnvelopeBus.receive()`. The `json.loads()` produced a `list`, and the code immediately called `data.get("envelope_kind")` — `AttributeError` because lists don't have `.get()`.
**Fix:** Added `isinstance(data, dict)` guard before attribute access. Non-dict JSON now raises `EnvelopeValidationError` with a descriptive message.
**Lesson:** First adversarial test to find a real bug. A JSON array is valid JSON but not a valid envelope — the code assumed `json.loads` always returns a dict.

### Entry 8 — SQLite Constraint as Defense
**Date:** 2026-02-26
**Problem:** Adversarial test attempted to swap two entries' `entry_hash` values via direct SQLite UPDATE. Hit `UNIQUE constraint failed: run_ledger.entry_hash`.
**Observation:** The UNIQUE constraint on `entry_hash` is itself a tamper defense — it prevents certain classes of manipulation (entry duplication, hash swapping) at the database level, even before `verify_chain()` runs. Rewrote test to target `previous_entry_hash` (which has no unique constraint) for the chain-linkage attack vector.
**Lesson:** Defense in depth works. The schema constraint catches attacks that verification logic would also catch, but earlier and with less code.

---

## Lessons Learned

1. **Fail-open crypto is worse than no crypto.** Auto-verifying on exception creates false confidence that's harder to detect than having no verification at all.
2. **The most sensitive operations need the strictest verification.** Waivers bypass mandatory gates — they should be the hardest artifact to create, not the easiest.
3. **Self-referential integrity is not integrity.** A hash chain that only verifies against itself proves consistency, not authenticity.
4. **Tests that only assert success are tests that only catch regressions.** Adversarial tests catch design flaws.
5. **Compress before you grow.** Every new feature multiplies the attack surface of every unresolved gap.
6. **Write the adversarial test first, then check if the code handles it.** The envelope bus JSON array bug was invisible to 135 happy-path tests. The first adversarial test found it.
7. **Schema constraints are defense in depth.** UNIQUE on `entry_hash` prevents hash-swap attacks at the DB level before verification logic even runs.

---

### Entry 9 — Trust Context: Key Fingerprint Recording
**Date:** 2026-02-26
**Problem:** No record of which signing keys were active when a ledger entry was created. A silent key rotation could invalidate historical entries without forensic visibility. Two runs using different trust roots look identical in the ledger.
**Fix:** Added `trust_context` dict field to `LedgerEntry` and SQLite schema. Contains `plugin_trust_root_fp`, `waiver_signing_key_fp`, `anchor_key_fp` — SHA-256 prefixes (16 hex chars) of the active public keys. Fingerprints are sealed into the entry hash, making post-hoc modification detectable. Orchestrator computes trust context at construction time and passes it through all transitions.
**Files changed:** `models/ledger.py`, `core/run_ledger.py` (schema + insert + read), `core/stage_machine.py` (pass-through), `core/orchestrator.py` (computation + wiring), `bridge/crypto_bridge.py` (new: `key_fingerprint`, `compute_trust_context`), `config.py` (new: key fields).
**Lesson:** Recording provenance at write time is cheap. Reconstructing it after the fact is impossible.

### Entry 10 — ADR-0007: CI Trust Boundary
**Date:** 2026-02-26
**Problem:** The threat model listed CI compromise as a Tier 3 threat but didn't explicitly state whether CI is inside the TCB for signing operations. This left an ambiguity: can a compromised CI forge valid artifacts?
**Fix:** ADR-0007 explicitly classifies CI as inside the TCB for plugin signing and anchor export, but outside the TCB for waiver signing. Key separation requirements documented. Trust model and runbook updated with CI-specific guidance and anchor storage domain separation.
**Lesson:** Implicit trust boundaries are non-boundaries. If a component can sign artifacts and you haven't said "this component is trusted to sign," you don't know what compromise means.

---

## Summary

**Final state:** 214 tests passing (135 original + 69 adversarial + 10 trust rotation). All hardening items implemented.
**Production code changes:** 9 files modified across two rounds. Zero new features. Zero API breaks. Backward compatible.
**Documentation:** 7 ADRs, threat model, operational runbook, hardening log.
**Tests added:** 9 test files in `tests/adversarial/`. 1 real bug found and fixed during writing.
