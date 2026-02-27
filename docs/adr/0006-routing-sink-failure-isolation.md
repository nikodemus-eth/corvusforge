# ADR-0006: Routing Sink Failure Isolation Design

**Status:** Accepted
**Date:** 2026-02-26
**Supersedes:** None

## Context

Invariant 9 states: "every event routes to all configured sinks." The `SinkDispatcher` sends pipeline events (envelopes) to all registered routing sinks (local file, email, Telegram, artifact store, etc.).

The critical question is: what happens when one sink fails?

If sink failure in one destination blocks delivery to all destinations, a single misconfigured email sink could halt the entire pipeline's event routing. If sink failures are silently swallowed, events are lost without detection.

## Decision

### Failure Isolation

Each sink is dispatched independently. A failure in one sink does not prevent dispatch to other sinks.

The `SinkDispatcher.dispatch()` method:

1. Iterates over all registered sinks.
2. Calls each sink's `send()` method in a `try/except Exception` block.
3. Records successes and failures separately.
4. Returns results for all sinks.
5. Raises `SinkDispatchError` only if *all* sinks fail.

### Failure Recording

Failed sink dispatches are logged with the exception details. The dispatch result includes both successful and failed sinks, so callers can inspect partial failure.

### All-Sinks-Fail Behavior

If every registered sink fails, `dispatch()` raises `SinkDispatchError`. This is the only case where a sink failure propagates as an exception. Rationale: if no sink can receive the event, the event is effectively lost, which violates Invariant 9.

If no sinks are registered, `dispatch()` returns an empty result (no error). Zero sinks is a valid configuration — it means routing is disabled.

### Batch Dispatch

`dispatch_batch()` applies the same isolation per envelope per sink. An envelope that fails all sinks is recorded in the batch result as failed. The batch continues processing remaining envelopes.

## Alternatives Considered

**A. Fail-fast on any sink error.** Stop dispatch on first failure. Rejected because it makes the reliability of the entire routing system dependent on the least reliable sink. One broken email server shouldn't prevent local file logging.

**B. Retry with backoff.** Retry failed sinks N times before marking as failed. Rejected for this phase — retry logic adds complexity and latency. A sink that fails on the first attempt usually fails on retry (configuration error, auth failure, network partition). Retry is appropriate for a future resilience layer, not the base dispatcher.

**C. Silent swallow on failure.** Catch and log, never raise. Rejected because the all-sinks-fail case represents genuine data loss. If no sink can receive an event, the system must signal this rather than pretend delivery succeeded.

**D. Circuit breaker pattern.** Track sink failure rates and temporarily disable failing sinks. Rejected for this phase — premature optimization. The current sink count is small (typically 1-3). Circuit breakers add value at scale.

## Consequences

- A single sink failure produces a warning log but does not block the pipeline.
- Callers that need guaranteed delivery to a specific sink must check dispatch results.
- The all-sinks-fail case is the only routing exception — this is intentionally restrictive.
- Sink implementors should handle their own retries if needed (e.g., an email sink could internally retry SMTP).
- The `SinkDispatchError` exception is the signal for "event routing is broken" — callers should treat it as a pipeline health issue.
