# ADR-0002: Waiver Signature Enforcement Model and Strict Mode

**Status:** Accepted
**Date:** 2026-02-26
**Supersedes:** None

## Context

Waivers bypass mandatory pipeline gates (accessibility audit at s5.5, security scan at s5.75). A waiver is the most powerful artifact in the system — it says "skip this safety check." The `WaiverArtifact` model has a `signature` field and an `approving_identity` field, but prior to this decision, neither was ever checked. Any caller could construct a `WaiverArtifact` with an arbitrary identity string and an empty signature, and it would register and activate.

This means any code path that can instantiate a `WaiverArtifact` can bypass any gate. The waiver system was functionally equivalent to a boolean flag with no authorization.

## Decision

### Signature Verification

`WaiverManager.register_waiver()` now verifies the `signature` field against `approving_identity` via the crypto bridge before registration:

- Empty or missing signature: `signature_verified = False`.
- Crypto bridge unavailable: `signature_verified = False`. Logged as warning.
- Verification exception: `signature_verified = False`. Fail-closed per ADR-0001.
- Valid signature: `signature_verified = True`.

Each waiver is stored with its verification status as metadata.

### Strict Mode

`WaiverManager` accepts a `require_signature: bool` parameter:

- `require_signature=False` (default): Unsigned waivers register normally but are flagged. `has_valid_waiver()` counts all non-expired waivers.
- `require_signature=True`: Unsigned waivers raise `WaiverSignatureError` on registration. `has_valid_waiver()` only counts signature-verified waivers.

### Environment Binding

Strict mode must be enabled in production. The production config guard (see ADR pending) enforces `require_signature=True` when `CORVUSFORGE_ENVIRONMENT=production`.

## Alternatives Considered

**A. Always require signatures.** Rejected because development environments typically lack saoe-core and cannot generate Ed25519 signatures. Requiring signatures everywhere would block local development.

**B. Warn-only mode.** Log unsigned waivers but never reject. Rejected because warnings in logs do not prevent gate bypass. The operational history of "warn and ignore" is that warnings are always ignored.

**C. Per-waiver override of strict mode.** Allow individual waivers to opt out of signature requirements. Rejected because this re-introduces the vulnerability at the waiver level — an attacker who can forge a waiver can also forge the "no signature needed" flag.

## Consequences

- Development workflows are unchanged (`require_signature=False` by default).
- Production environments must provide signing infrastructure or cannot register waivers.
- `WaiverSignatureError` is a new exception type that callers must handle.
- The waiver storage format now includes `signature_verified` metadata in the content-addressed store.
- Gate bypass in production now requires possession of a signing key, not just code access.
