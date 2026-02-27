# Corvusforge

**Deterministic | Auditable | Contract-Driven Coding Pipeline**

Built on [SAOE](https://github.com/nikodemus-eth/saoe-mvp) | Powered by Thingstead

**v0.3.0 PRODUCTION** — Private repo by default.

```bash
pip install corvusforge==0.3.0
corvusforge ui          # Full Streamlit dashboard
corvusforge new         # Start a pipeline run
corvusforge demo        # End-to-end demo
corvusforge plugins     # List installed DLC plugins
```

## Core Invariants (16)

1. Secrets never transit. SAOE buckets enforce isolation.
2. Only contracted JSON envelopes move between nodes.
3. Execution semantics never depend on request source.
4. No stage runs unless prerequisites are satisfied.
5. Accessibility is a mandatory gate (WCAG 2.1 AA).
6. Security is a mandatory gate (static analysis + secrets scan).
7. All state transitions recorded in append-only Run Ledger.
8. All artifacts are content-addressed and immutable.
9. Every event routes to all configured sinks.
10. Every run is replayable and resumable deterministically.
11. All agentic execution inside Thingstead fleets.
12. Persistent memory in .openclaw-data.
13. Signed DLC plugins (ToolGate + SATL).
14. Full Multi-Agent UI dashboard.
15. DLC Marketplace (local-first + signed).
16. Production hardening (Docker, CI/CD, config, observability).

## Pipeline Stages

| Stage | Name | Type |
|-------|------|------|
| 0 | Intake | Entry |
| 1 | Prerequisites Synthesis | Planning |
| 2 | Environment Readiness | Setup |
| 3 | Test Contracting | Specification |
| 4 | Code Plan | Design |
| 5 | Implementation | Build |
| 5.5 | Accessibility Gate | Mandatory Gate |
| 5.75 | Security Gate | Mandatory Gate |
| 6 | Verification | Quality |
| 7 | Release and Attestation | Delivery |

## Architecture

The Build Monitor is a projection of the Run Ledger. It does not compute truth. It displays it.

Every run is replayable. Every transition is ledger-recorded. Every artifact is content-addressed.

## Production Deployment

```bash
# Local
pip install corvusforge[prod]==0.3.0
corvusforge ui

# Docker
docker-compose up --build

# CI/CD
git push  # triggers full test + Docker build
```

See [CHANGELOG.md](CHANGELOG.md) and [RELEASE_NOTES_v0.3.0.md](RELEASE_NOTES_v0.3.0.md) for details.

---

Status: v0.3.0 production-grade. Foundation locked. Ready for enterprise.
