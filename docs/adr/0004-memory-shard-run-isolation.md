# ADR-0004: Memory Shard Run Isolation and Snapshot Semantics

**Status:** Accepted
**Date:** 2026-02-26
**Supersedes:** None

## Context

Thingstead's `MemoryShard` model stores fleet-generated knowledge (insights, patterns, meta-observations) as content-addressed, immutable records. Prior to this decision, shards had no `run_id` field. All shards from all runs accumulated in a single namespace, queryable only by `fleet_id` and `tags`.

This creates two problems:

1. **Replay non-determinism.** Invariant 10 requires runs to be "replayable and resumable deterministically." If a replay sees shards from the original run *plus* shards from intervening runs, its behavior diverges from the original execution.

2. **Integrity drift.** Without a way to snapshot the exact memory state at a given run, there is no way to verify that the memory a fleet consumed during run N is the same memory that would be consumed during a replay of run N.

## Decision

### Run Scoping

`MemoryShard` gains a `run_id: str` field (default `""` for backward compatibility with pre-hardening shards).

`write_shard()` accepts an optional `run_id` parameter. When provided, the shard is tagged with that run.

`query_shards()` accepts an optional `run_id` parameter. When provided, only shards from that run are returned.

### Integrity Verification

`verify_shard(shard)` re-hashes the shard's `content` and compares the result to `content_hash`. If they differ, `ShardIntegrityError` is raised.

This catches post-write tampering (content modified but hash not updated) and hash collision attacks (different content, same hash — computationally infeasible with SHA-256 but worth checking).

### Per-Run Snapshots

`snapshot_for_run(run_id, *, verify=True)` returns all shards for a given run. If `verify=True`, every shard's integrity is checked before inclusion. This provides a verifiable, isolated view of fleet memory for a specific run.

### Backward Compatibility

- Shards without `run_id` (pre-hardening) have `run_id=""`.
- `query_shards()` without `run_id` returns all shards (legacy behavior preserved).
- `snapshot_for_run()` with an empty `run_id` returns legacy shards.

## Alternatives Considered

**A. Separate shard stores per run.** Each run gets its own directory/database. Rejected because it complicates cross-run querying (fleets may legitimately need historical context) and multiplies storage management.

**B. Versioned shard references.** Store a "shard manifest" per run listing which existing shards were visible. Rejected because it adds indirection without simplifying the model — the manifest itself needs integrity checking.

**C. Immutable shard database with WAL.** Use SQLite WAL mode for shards (like the ledger). Rejected because shards are already content-addressed and immutable — the JSON store is sufficient. Adding SQLite would be architectural escalation for marginal benefit.

## Consequences

- Fleet code must pass `run_id` when writing shards for deterministic replay to work.
- Legacy shards (pre-hardening) remain accessible but are not attributable to any run.
- `ShardIntegrityError` is a new exception that consumers of `snapshot_for_run()` must handle.
- The `verify=True` default on snapshots adds O(n) hash recomputation on read. This is the correct default — integrity should be verified, not assumed.
