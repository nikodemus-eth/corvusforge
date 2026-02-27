# ADR-0005: Build Monitor as Projection of Ledger, Not Logs

**Status:** Accepted
**Date:** 2026-02-26
**Supersedes:** None

## Context

The Build Monitor (`monitor/projection.py`, `monitor/renderer.py`) provides a real-time view of pipeline state: which stages have run, their status, active waivers, and integrity indicators. The question is: what is the source of truth for this view?

Two options exist:

1. **Log-based:** The monitor reads application logs, parses them, and reconstructs state. This is the pattern used by most CI dashboards.
2. **Ledger-based:** The monitor projects its view directly from `RunLedger` entries. The ledger is the single source of truth; the monitor is a read-only projection.

## Decision

The Build Monitor is a projection of the `RunLedger`, not application logs.

`MonitorProjection` reads ledger entries for a given `run_id` and derives:

- Stage states (from transition entries)
- Input/output hashes (from ledger payloads)
- Artifact references (from ledger payloads)
- Waiver presence (from waiver-type entries)
- Chain integrity (from `verify_chain()`)

The monitor never writes to the ledger. It never maintains independent state that could drift from the ledger. It is a pure function: `f(ledger_entries) -> monitor_view`.

## Alternatives Considered

**A. Log-based monitor.** Parse structured logs for state changes. Rejected because:
- Logs can be lost, reordered, or duplicated.
- Log parsing is fragile (format changes break the monitor).
- Logs are not tamper-evident. The ledger is.
- Two sources of truth (logs + ledger) create divergence risk.

**B. Event-sourced monitor with own store.** Monitor subscribes to pipeline events and builds its own database. Rejected because it duplicates the ledger's role and creates a consistency problem (what happens when the monitor's DB disagrees with the ledger?).

**C. Hybrid: ledger for immutable state, logs for ephemeral.** Use ledger for stage transitions but logs for progress updates and timing. Acceptable as a future evolution, but for now the ledger contains all necessary data and the simpler model is preferred.

## Consequences

- The monitor is guaranteed to be consistent with the ledger at all times. If the ledger shows a stage as PASSED, the monitor shows it as PASSED.
- Monitor performance is bounded by ledger query performance. For large runs, this may require indexed queries (current SQLite implementation handles this).
- The monitor can verify chain integrity on each refresh, providing continuous tamper detection.
- The monitor cannot show information that isn't in the ledger. If a stage handler produces console output that isn't recorded in a ledger entry, the monitor won't display it.
- This pattern (projection from immutable log) is the same pattern used by event-sourced systems. If Corvusforge evolves toward event sourcing, the monitor is already aligned.
