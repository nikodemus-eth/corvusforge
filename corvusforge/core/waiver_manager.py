"""Waiver management — structured waiver artifacts, never informal flags.

Waivers allow mandatory gates (accessibility, security) to be bypassed
with explicit justification, expiration, and risk classification.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from corvusforge.core.artifact_store import ContentAddressedStore
from corvusforge.core.hasher import canonical_json_bytes
from corvusforge.models.waivers import WaiverArtifact


class WaiverExpiredError(RuntimeError):
    """Raised when attempting to use an expired waiver."""


class WaiverManager:
    """Validates, stores, and checks waivers.

    Every waiver is stored as a content-addressed artifact.
    The Build Monitor displays active waivers prominently.

    Parameters
    ----------
    artifact_store:
        The content-addressed store for persisting waivers.
    """

    def __init__(self, artifact_store: ContentAddressedStore) -> None:
        self._store = artifact_store
        # In-memory registry: scope -> list of waiver_ids
        self._waivers: dict[str, list[WaiverArtifact]] = {}

    def register_waiver(self, waiver: WaiverArtifact) -> str:
        """Validate and store a waiver artifact.

        Returns the content address of the stored waiver.
        """
        if waiver.is_expired:
            raise WaiverExpiredError(
                f"Waiver {waiver.waiver_id} expired at {waiver.expiration}"
            )

        # Store as content-addressed artifact
        waiver_bytes = canonical_json_bytes(waiver.model_dump(mode="json"))
        stored = self._store.store(
            waiver_bytes,
            name=f"waiver-{waiver.waiver_id}",
            artifact_type="waiver",
            metadata={"scope": waiver.scope, "risk": waiver.risk_classification.value},
        )

        # Register in memory
        if waiver.scope not in self._waivers:
            self._waivers[waiver.scope] = []
        self._waivers[waiver.scope].append(waiver)

        return stored.content_address

    def has_valid_waiver(self, scope: str) -> bool:
        """Check if there is a non-expired waiver for the given scope."""
        waivers = self._waivers.get(scope, [])
        return any(not w.is_expired for w in waivers)

    def get_waivers(self, scope: str) -> list[WaiverArtifact]:
        """Return all waivers for a scope (including expired)."""
        return list(self._waivers.get(scope, []))

    def get_active_waivers(self, scope: str) -> list[WaiverArtifact]:
        """Return only non-expired waivers for a scope."""
        return [w for w in self._waivers.get(scope, []) if not w.is_expired]

    def get_all_active_waivers(self) -> list[WaiverArtifact]:
        """Return all non-expired waivers across all scopes."""
        result = []
        for waivers in self._waivers.values():
            result.extend(w for w in waivers if not w.is_expired)
        return result
