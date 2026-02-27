"""Waiver artifact models — structured, never informal flags."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class RiskClassification(str, Enum):
    """Risk level assigned to a waiver."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class WaiverArtifact(BaseModel):
    """A structured waiver allowing a mandatory gate to be bypassed.

    Waivers are content-addressed artifacts stored in the artifact store.
    They are never informal flags — each carries scope, justification,
    expiration, and a cryptographic signature from the approving identity.

    The Build Monitor displays waivers prominently.
    """

    model_config = ConfigDict(frozen=True)

    waiver_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    scope: str  # stage_id or specific check identifier
    justification: str
    expiration: datetime
    approving_identity: str  # Ed25519 public key fingerprint or human identifier
    risk_classification: RiskClassification
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    signature: str = ""  # Ed25519 signature over canonical waiver bytes (set after signing)

    @property
    def is_expired(self) -> bool:
        """Check if this waiver has passed its expiration date."""
        return datetime.now(timezone.utc) > self.expiration
