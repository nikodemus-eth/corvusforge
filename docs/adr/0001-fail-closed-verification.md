# ADR-0001: Fail-Closed Verification for Plugins and DLC Packages

**Status:** Accepted
**Date:** 2026-02-26
**Supersedes:** None

## Context

Plugin verification (`registry.py:verify_plugin()`) and DLC verification (`loader.py:verify_dlc()`) both used `try/except` patterns that caught all exceptions and set `verified=True` as a fallback. This created a fail-open crypto path: if the crypto bridge threw an error, was unavailable, or encountered an unexpected condition, the plugin was silently promoted to "verified" status.

This is categorically worse than having no verification at all, because it creates false assurance. A system with no verification makes no claims. A system that says "verified" when verification was never performed makes a false claim that downstream components trust.

The self-attestation problem compounds this: plugins supply their own public key for signature verification. A plugin author who controls both the payload and the key can always produce a valid signature. But at minimum, the verification path must not auto-approve when the crypto check *cannot even run*.

## Decision

All verification functions must return `False` (unverified) on any error path:

1. **Crypto bridge unavailable:** Return `False`. Log a warning.
2. **Exception during verification:** Return `False`. Log the exception.
3. **Signature absent or empty:** Return `False`.
4. **Signature invalid:** Return `False`.
5. **Only path to `True`:** Crypto bridge available, signature present, signature cryptographically valid.

No exception handler may set `verified=True`. No fallback may assume validity.

## Alternatives Considered

**A. Fail-open with logging.** The previous behavior. Rejected because logging does not prevent the verified flag from propagating through downstream trust decisions.

**B. Fail-closed with retry.** Retry verification N times before giving up. Rejected because a transient crypto failure should not become a trust decision. If verification cannot succeed now, the plugin is unverified now. It can be re-verified later.

**C. Separate "verification_attempted" flag.** Track whether verification was attempted vs. succeeded. Rejected for this phase — adds complexity without changing the security property. The relevant question is "is it verified?", not "did we try?".

## Consequences

- Plugins that were previously auto-verified in environments without saoe-core will now show as unverified. This is the correct state.
- Development workflows without crypto infrastructure will see all plugins as unverified. This is acceptable — unverified plugins still load, they just aren't trusted.
- If a future "block unverified plugins" mode is added, it will be safe to implement because the verified flag now has integrity.
- Self-attestation remains an open problem (ADR pending for trust root design). This ADR only closes the "auto-promote on failure" vulnerability.
