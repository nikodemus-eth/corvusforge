"""Content-addressed artifact models (Invariant 8: immutable)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ArtifactRef(BaseModel):
    """A reference to a content-addressed artifact.

    The content_address is the SHA-256 hex digest of the artifact bytes.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    content_address: str  # "sha256:<hex>"
    artifact_type: str = "generic"
    size_bytes: int = 0


class ContentAddressedArtifact(BaseModel):
    """Metadata for a stored artifact — the bytes themselves live in the store.

    Artifacts are immutable once stored. There is no update or delete operation.
    The content_address is both the identity and the integrity check.
    """

    model_config = ConfigDict(frozen=True)

    content_address: str  # "sha256:<hex>"
    artifact_type: str
    name: str
    size_bytes: int
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: dict[str, Any] = {}


class ArtifactManifest(BaseModel):
    """A collection of artifact references for a stage output."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    stage_id: str
    artifacts: list[ArtifactRef]
    manifest_hash: str = ""  # SHA-256 of canonical(sorted artifact refs)
