"""Content-addressed, immutable artifact store (Invariant 8).

Storage layout: {base_path}/{sha256[0:2]}/{sha256[2:4]}/{sha256}.dat
No delete method — artifacts are immutable once stored.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from corvusforge.core.hasher import sha256_hex
from corvusforge.models.artifacts import ArtifactRef, ContentAddressedArtifact


class ArtifactIntegrityError(RuntimeError):
    """Raised when a stored artifact's hash does not match its address."""


class ContentAddressedStore:
    """SHA-256 keyed, immutable artifact store.

    Every artifact is stored under its SHA-256 digest. Storing the same
    content twice is a no-op (idempotent). There is no update or delete.

    Parameters
    ----------
    base_path:
        Root directory for artifact storage.
    """

    def __init__(self, base_path: Path) -> None:
        self._base = Path(base_path)
        self._base.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _extract_digest(content_address: str) -> str:
        """Strip the ``sha256:`` prefix from a content address, if present."""
        return content_address.removeprefix("sha256:")

    def _artifact_path(self, sha256_digest: str) -> Path:
        """Compute the storage path for a SHA-256 digest.

        Layout: {base}/{sha256[0:2]}/{sha256[2:4]}/{sha256}.dat
        """
        return self._base / sha256_digest[:2] / sha256_digest[2:4] / f"{sha256_digest}.dat"

    # ------------------------------------------------------------------
    # Store
    # ------------------------------------------------------------------

    def store(
        self,
        data: bytes,
        *,
        name: str = "",
        artifact_type: str = "generic",
        metadata: dict[str, Any] | None = None,
    ) -> ContentAddressedArtifact:
        """Store data and return its content-addressed artifact metadata.

        If the content already exists (same hash), verifies integrity
        and returns the existing artifact without overwriting.
        """
        digest = sha256_hex(data)
        path = self._artifact_path(digest)

        if path.exists():
            # Verify existing content matches
            if not self.verify(digest):
                raise ArtifactIntegrityError(
                    f"Existing artifact at {digest} failed integrity check"
                )
        else:
            # Write new artifact
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        return ContentAddressedArtifact(
            content_address=f"sha256:{digest}",
            artifact_type=artifact_type,
            name=name or digest[:16],
            size_bytes=len(data),
            metadata=metadata or {},
        )

    # ------------------------------------------------------------------
    # Retrieve
    # ------------------------------------------------------------------

    def retrieve(self, content_address: str) -> bytes:
        """Retrieve artifact bytes by content address.

        Parameters
        ----------
        content_address:
            Either "sha256:<hex>" or just the hex digest.
        """
        digest = self._extract_digest(content_address)
        path = self._artifact_path(digest)
        if not path.exists():
            raise FileNotFoundError(f"Artifact not found: {content_address}")
        return path.read_bytes()

    # ------------------------------------------------------------------
    # Check and verify
    # ------------------------------------------------------------------

    def exists(self, content_address: str) -> bool:
        """Check if an artifact exists in the store."""
        return self._artifact_path(self._extract_digest(content_address)).exists()

    def verify(self, content_address: str) -> bool:
        """Re-hash stored data and compare against the content address.

        Returns True if the stored bytes match the expected hash.
        """
        digest = self._extract_digest(content_address)
        path = self._artifact_path(digest)
        if not path.exists():
            return False
        return sha256_hex(path.read_bytes()) == digest

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def make_ref(
        self,
        content_address: str,
        name: str = "",
        artifact_type: str = "generic",
    ) -> ArtifactRef:
        """Create an ArtifactRef for a stored artifact."""
        digest = self._extract_digest(content_address)
        path = self._artifact_path(digest)
        size = path.stat().st_size if path.exists() else 0
        return ArtifactRef(
            name=name or digest[:16],
            content_address=f"sha256:{digest}",
            artifact_type=artifact_type,
            size_bytes=size,
        )
