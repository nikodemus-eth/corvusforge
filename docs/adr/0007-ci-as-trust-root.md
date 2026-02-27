# ADR-0007: CI as Trust Root — Signing Authority and Trust Boundary

**Status:** Accepted
**Date:** 2026-02-26
**Supersedes:** None

## Context

The threat model (docs/security/threat-model.md) identifies CI/CD pipeline compromise as a Tier 3 threat — the highest-impact scenario. The question that was previously implicit and must now be answered explicitly:

**Is CI trusted to sign artifacts?**

If CI holds signing keys and can produce validly signed plugins, waivers, and anchors, then CI is inside the Trusted Computing Base (TCB). A compromised CI pipeline can forge any artifact the system considers authentic.

If CI does not hold signing keys, then signing is offline-only and CI is outside the TCB for signing operations. A compromised CI can still execute code and modify files, but it cannot produce artifacts that pass signature verification.

This distinction changes the security posture of the entire system. It must not be left implicit.

## Decision

### CI is inside the TCB for signing operations.

For the current deployment model, CI holds signing keys and is authorized to:

1. Sign plugins as part of the build/release process.
2. Generate anchor exports after pipeline runs.
3. Record trust context fingerprints in ledger entries.

CI is **not** authorized to:

1. Sign waivers. Waiver signing keys must be held by authorized human approvers, not CI. Waivers bypass safety gates — they require human judgment and accountability.
2. Modify the Corvusforge source code's verification logic. Code changes are gated by code review, not CI signing.

### Consequences of CI being in the TCB

1. **CI signing keys are production keys.** They must be stored in CI secrets managers with access controls, not in plaintext configuration.
2. **CI key rotation is production key rotation.** The rotation procedure in the runbook applies to CI keys.
3. **CI key compromise requires the full incident response.** A leaked CI signing key means all plugins signed by that key since the last known-good state are suspect.
4. **Key fingerprints in ledger entries identify CI-signed vs. human-signed.** Because the trust context records which key was active, forensic analysis can distinguish CI-produced entries from human-produced entries.

### Waiver signing is offline-only

Waivers are explicitly excluded from CI signing authority. Rationale:

- Waivers bypass mandatory safety gates (accessibility, security).
- A compromised CI with waiver signing keys can silently disable all gates.
- Waiver signing requires a human identity (`approving_identity`) that maps to a person, not a service account.
- The operational cost of offline waiver signing is low (waivers are infrequent).

### Key separation requirements

| Key Type | Holder | Environment | Can CI use it? |
|----------|--------|-------------|----------------|
| Plugin signing key | CI secrets manager | CI only | Yes |
| Anchor export key | CI secrets manager | CI only | Yes |
| Waiver signing key | Human approver | Local only | No |

### Fingerprint recording makes this auditable

Every ledger entry records `trust_context` with fingerprints of the active keys. This means:

- An entry signed by CI's plugin key has CI's fingerprint.
- An entry created during a local dev run has a different (or empty) fingerprint.
- A key rotation is visible as a fingerprint boundary in the ledger.
- If CI's key is compromised, all entries with that fingerprint can be identified for audit.

## Alternatives Considered

**A. CI is fully outside the TCB (offline signing only).** All signing happens on a developer's machine before CI runs. CI only verifies signatures, never creates them. Rejected for this phase because it requires a signing workflow that doesn't exist yet (sign-then-push-then-CI-verify). This is the correct long-term direction but not the current operational reality.

**B. CI signs everything (including waivers).** Simpler operationally — CI has full authority. Rejected because it makes CI compromise equivalent to full system compromise. Waiver signing is the most dangerous capability and must be separated.

**C. Hardware Security Modules (HSMs) for CI signing.** CI signing keys are held in an HSM that CI calls via API. The key never leaves the HSM. Rejected for this phase as over-engineering — HSM integration is appropriate for high-security deployments but adds significant operational complexity.

**D. Short-lived CI signing keys.** CI receives a temporary signing key per build from a key management service. The key expires after the build. Rejected for this phase — the key management infrastructure doesn't exist. This is a good future evolution.

## Consequences

- CI operators must treat CI signing keys with the same care as production database credentials.
- Key fingerprints in ledger entries create a forensic trail that can be audited after a CI compromise.
- The waiver signing exclusion means production waiver creation requires a human with a local signing key, which adds friction. This friction is intentional — it's the security property.
- Future evolution toward offline-only signing (Alternative A) or HSM-backed CI signing (Alternative C) is compatible with this ADR. The key fingerprint recording ensures the transition is visible in the ledger.
- This ADR must be revisited if the deployment model changes (e.g., multi-tenant, SaaS, or zero-trust CI).
