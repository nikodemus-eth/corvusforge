# ADR-0003: External Ledger Anchoring Design and Trust Domain Boundaries

**Status:** Accepted
**Date:** 2026-02-26
**Supersedes:** None

## Context

The `RunLedger` uses a hash-chained, append-only SQLite store. Each entry's `entry_hash` is computed over its payload plus the `previous_entry_hash`, forming a Merkle-like chain. `verify_chain()` walks the chain and recomputes all hashes.

This detects tampering *since the last trusted state* — if an attacker modifies an entry, the downstream hashes won't match. But it does not detect a full chain rewrite: an adversary with write access to the SQLite file can delete all entries, re-insert modified entries, and recompute all hashes from scratch. `verify_chain()` will pass because the chain is internally consistent.

The hash chain proves consistency, not authenticity. It answers "has this chain been modified since it was written?" only if you trust the writer. It does not answer "is this the same chain that was written during the original run?"

## Decision

### Anchor Export

`RunLedger.export_anchor(run_id)` returns a tamper-evident anchor dict:

```python
{
    "run_id": "cf-...",
    "entry_count": 47,
    "root_hash": "<hash of last entry>",
    "first_entry_hash": "<hash of first entry>",
    "timestamp_utc": "2026-02-26T...",
    "anchor_hash": "<SHA-256 of canonical JSON of above fields>"
}
```

The `anchor_hash` covers all fields, making the anchor itself tamper-evident.

### Anchor Verification

`RunLedger.verify_against_anchor(run_id, anchor)` checks:

1. Current entry count >= anchor's `entry_count` (detect truncation).
2. First entry's hash matches `first_entry_hash` (detect retroactive rewrite).
3. Entry at position `entry_count - 1` matches `root_hash` (detect modification).
4. Full chain verification (existing `verify_chain()` logic).

### Trust Domain

The anchor is only useful if stored *outside the ledger's trust domain*:

- Same SQLite file: useless (attacker rewrites both).
- Separate local file: marginally better (attacker needs two file writes).
- External service (S3, transparency log, email): meaningful (attacker needs separate credentials).
- Multiple independent witnesses: strongest (attacker must compromise all).

This ADR does not mandate a specific storage backend for anchors. It provides the export/verify API. Operational deployment (see runbook) determines where anchors are stored.

## Alternatives Considered

**A. Signed ledger entries.** Sign each entry with a run-specific key. Rejected because it requires key management infrastructure that doesn't exist yet, and signing every entry adds significant overhead. Anchoring provides similar assurance with a single export per run.

**B. Merkle tree with published root.** Build a full Merkle tree and publish the root hash. Rejected as over-engineering for the current scale. The linear chain with external root anchoring provides equivalent tamper evidence for append-only chains.

**C. Blockchain-style distributed ledger.** Rejected. The threat model is not Byzantine — it's a single-writer system where we want to detect compromise after the fact, not prevent it in real time.

## Consequences

- Anchors must be exported and stored as part of the release process (operational requirement).
- Anchor verification is O(n) in ledger entries — acceptable for current scale.
- Empty runs produce anchors with `entry_count: 0` — no special handling needed.
- Anchors are append-only checkpoints: you can export multiple anchors for the same run at different points. Later anchors don't invalidate earlier ones.
- The trust boundary is now explicit: the ledger is trusted for consistency, anchors are trusted for authenticity, and the two together provide full tamper evidence.
