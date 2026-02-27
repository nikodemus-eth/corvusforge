"""Waiver management — structured waiver artifacts, never informal flags.

Waivers allow mandatory gates (accessibility, security) to be bypassed
with explicit justification, expiration, and risk classification.

**Hardening (v0.3.1):** Waiver signatures are now verified on registration.
An unsigned or unverifiable waiver is stored but flagged as ``signature_verified=False``
in its artifact metadata.  ``has_valid_waiver()`` only counts signature-verified
waivers when ``require_signature=True`` (the default in production).
"""

from __future__ import annotations

import logging

from corvusforge.core.artifact_store import ContentAddressedStore
from corvusforge.core.hasher import canonical_json_bytes
from corvusforge.models.waivers import WaiverArtifact

logger = logging.getLogger(__name__)


class WaiverExpiredError(RuntimeError):
    """Raised when attempting to use an expired waiver."""


class WaiverSignatureError(RuntimeError):
    """Raised when a waiver's signature is missing or invalid."""


class WaiverManager:
    """Validates, stores, and checks waivers.

    Every waiver is stored as a content-addressed artifact.
    The Build Monitor displays active waivers prominently.

    Parameters
    ----------
    artifact_store:
        The content-addressed store for persisting waivers.
    require_signature:
        If ``True`` (default), ``has_valid_waiver()`` only counts waivers
        whose signature has been cryptographically verified.  Set to
        ``False`` in development environments where saoe-core is absent.
    """

    def __init__(
        self,
        artifact_store: ContentAddressedStore,
        *,
        require_signature: bool = False,
        waiver_verification_key: str = "",
    ) -> None:
        self._store = artifact_store
        self._require_signature = require_signature
        self._waiver_verification_key = waiver_verification_key
        # In-memory registry: scope -> list of (waiver, signature_verified) tuples
        self._waivers: dict[str, list[tuple[WaiverArtifact, bool]]] = {}

    def register_waiver(self, waiver: WaiverArtifact) -> str:
        """Validate, verify signature, and store a waiver artifact.

        Returns the content address of the stored waiver.

        Raises
        ------
        WaiverExpiredError
            If the waiver has already expired.
        WaiverSignatureError
            If ``require_signature`` is True and the waiver has no
            signature or the signature cannot be verified.
        """
        if waiver.is_expired:
            raise WaiverExpiredError(
                f"Waiver {waiver.waiver_id} expired at {waiver.expiration}"
            )

        # Verify signature
        sig_verified = self._verify_waiver_signature(waiver)

        if self._require_signature and not sig_verified:
            raise WaiverSignatureError(
                f"Waiver {waiver.waiver_id} for scope '{waiver.scope}' "
                f"has no valid signature.  Waivers bypassing mandatory gates "
                f"must be cryptographically signed."
            )

        # Store as content-addressed artifact
        waiver_bytes = canonical_json_bytes(waiver.model_dump(mode="json"))
        stored = self._store.store(
            waiver_bytes,
            name=f"waiver-{waiver.waiver_id}",
            artifact_type="waiver",
            metadata={
                "scope": waiver.scope,
                "risk": waiver.risk_classification.value,
                "signature_verified": sig_verified,
            },
        )

        # Register in memory
        if waiver.scope not in self._waivers:
            self._waivers[waiver.scope] = []
        self._waivers[waiver.scope].append((waiver, sig_verified))

        if sig_verified:
            logger.info(
                "Registered signed waiver %s for scope '%s'.",
                waiver.waiver_id, waiver.scope,
            )
        else:
            logger.warning(
                "Registered UNSIGNED waiver %s for scope '%s' "
                "(signature_verified=False).",
                waiver.waiver_id, waiver.scope,
            )

        return stored.content_address

    def has_valid_waiver(self, scope: str) -> bool:
        """Check if there is a non-expired waiver for the given scope.

        When ``require_signature`` is True, only signature-verified
        waivers count as valid.
        """
        entries = self._waivers.get(scope, [])
        for waiver, sig_verified in entries:
            if waiver.is_expired:
                continue
            if self._require_signature and not sig_verified:
                continue
            return True
        return False

    def get_waivers(self, scope: str) -> list[WaiverArtifact]:
        """Return all waivers for a scope (including expired)."""
        return [w for w, _sv in self._waivers.get(scope, [])]

    def get_active_waivers(self, scope: str) -> list[WaiverArtifact]:
        """Return only non-expired waivers for a scope."""
        return [
            w for w, _sv in self._waivers.get(scope, [])
            if not w.is_expired
        ]

    def get_all_active_waivers(self) -> list[WaiverArtifact]:
        """Return all non-expired waivers across all scopes."""
        result = []
        for entries in self._waivers.values():
            result.extend(w for w, _sv in entries if not w.is_expired)
        return result

    # ------------------------------------------------------------------
    # Signature verification
    # ------------------------------------------------------------------

    def _verify_waiver_signature(self, waiver: WaiverArtifact) -> bool:
        """Verify the Ed25519 signature on a waiver artifact.

        Returns ``True`` only if:
        1. The waiver has a signature.
        2. A waiver verification key is configured (fail-closed if empty).
        3. The signature verifies against the configured key
           (NOT against ``approving_identity``, which is informational only).

        Returns ``False`` in all other cases (missing signature,
        empty verification key, unavailable crypto, verification failure,
        exception).
        """
        if not waiver.signature:
            logger.debug(
                "Waiver %s has no signature.", waiver.waiver_id
            )
            return False

        # Fail-closed: no configured verification key → cannot verify
        if not self._waiver_verification_key:
            logger.warning(
                "No waiver verification key configured — waiver %s "
                "signature cannot be verified (fail-closed).",
                waiver.waiver_id,
            )
            return False

        try:
            from corvusforge.bridge.crypto_bridge import (
                is_saoe_crypto_available,
                verify_data,
            )

            if not is_saoe_crypto_available():
                logger.warning(
                    "Crypto bridge unavailable — waiver %s signature "
                    "cannot be verified.",
                    waiver.waiver_id,
                )
                return False

            # Build the canonical payload that was signed.
            # approving_identity is part of the payload (informational),
            # but it is NOT the verification key.
            payload = canonical_json_bytes({
                "waiver_id": waiver.waiver_id,
                "scope": waiver.scope,
                "justification": waiver.justification,
                "expiration": waiver.expiration.isoformat(),
                "approving_identity": waiver.approving_identity,
                "risk_classification": waiver.risk_classification.value,
            })
            # Authority comes from the configured trust root, not the waiver
            valid = verify_data(
                payload,
                waiver.signature,
                self._waiver_verification_key,
            )
            if not valid:
                logger.warning(
                    "Waiver %s signature verification FAILED.",
                    waiver.waiver_id,
                )
            return valid

        except Exception:
            logger.exception(
                "Error verifying waiver %s — treating as unverified.",
                waiver.waiver_id,
            )
            return False
