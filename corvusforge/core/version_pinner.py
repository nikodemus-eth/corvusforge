"""Version pinning — records and enforces version pins per run (Invariant 10).

Each run records its exact pipeline_version, schema_version, accessibility
and security ruleset versions, and toolchain version. This ensures that
any replay uses identical semantics.
"""

from __future__ import annotations

from corvusforge.core.hasher import compute_environment_snapshot_hash
from corvusforge.models.versioning import VersionPin


class VersionDriftError(RuntimeError):
    """Raised when current versions don't match the pinned versions for a run."""


class VersionPinner:
    """Records and enforces version pins for pipeline runs.

    At run creation, the current versions are pinned. On resume or replay,
    the pinner detects drift by comparing current vs. recorded versions.
    """

    def __init__(self, current_pin: VersionPin | None = None) -> None:
        self._current = current_pin or VersionPin()

    @property
    def current_pin(self) -> VersionPin:
        """Return the current version pin."""
        return self._current

    def environment_hash(self, env_vars: dict[str, str] | None = None) -> str:
        """Compute the environment snapshot hash for the current pin."""
        return compute_environment_snapshot_hash(self._current, env_vars)

    def check_drift(
        self,
        recorded_pin: VersionPin,
        *,
        strict: bool = True,
    ) -> list[str]:
        """Compare current versions against a recorded pin.

        Returns a list of drift descriptions. Empty list means no drift.
        Raises VersionDriftError if strict=True and drift is detected.
        """
        drifts: list[str] = []
        current = self._current.model_dump()
        recorded = recorded_pin.model_dump()

        for field, current_val in current.items():
            recorded_val = recorded.get(field)
            if current_val != recorded_val:
                drifts.append(
                    f"{field}: recorded={recorded_val!r}, current={current_val!r}"
                )

        if strict and drifts:
            raise VersionDriftError(
                f"Version drift detected: {'; '.join(drifts)}"
            )

        return drifts
