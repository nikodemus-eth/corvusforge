"""Contracted inter-node transport envelopes (Invariant 2).

All node communication uses validated JSON envelopes. No freeform messages.
Each envelope is a frozen Pydantic model with schema validation on construction.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EnvelopeKind(str, Enum):
    """The six contracted envelope types."""

    WORK_ORDER = "work_order"
    EVENT = "event"
    ARTIFACT = "artifact"
    CLARIFICATION = "clarification"
    FAILURE = "failure"
    RESPONSE = "response"


class EnvelopeBase(BaseModel):
    """Base fields shared by all envelope types.

    Every inter-node message carries these fields for traceability,
    routing, and security. The payload_hash ensures integrity.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: str = "2026-02"
    envelope_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    source_node_id: str
    destination_node_id: str
    request_source: str = ""  # e.g. "cli", "api", "agent"
    request_source_ref: str = ""  # reference back to the originating request
    payload_hash: str = ""  # SHA-256 of canonical payload bytes
    allowed_next_actions: list[str] = []
    timestamp_utc: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    envelope_kind: EnvelopeKind


class WorkOrderEnvelope(EnvelopeBase):
    """Instructs a node to perform work on a specific stage."""

    envelope_kind: EnvelopeKind = EnvelopeKind.WORK_ORDER
    stage_id: str
    work_specification: dict[str, Any] = {}


class EventEnvelope(EnvelopeBase):
    """Reports a state transition or significant event."""

    envelope_kind: EnvelopeKind = EnvelopeKind.EVENT
    event_type: str  # e.g. "stage_transition", "artifact_stored"
    stage_id: str
    details: dict[str, Any] = {}


class ArtifactEnvelope(EnvelopeBase):
    """References a content-addressed artifact produced by a stage."""

    envelope_kind: EnvelopeKind = EnvelopeKind.ARTIFACT
    artifact_ref: str  # content-addressed key "sha256:<hex>"
    artifact_type: str
    size_bytes: int = 0


class ClarificationEnvelope(EnvelopeBase):
    """Requests clarification from the operator when a stage is blocked."""

    envelope_kind: EnvelopeKind = EnvelopeKind.CLARIFICATION
    question: str
    context: dict[str, Any] = {}
    blocking_stage_id: str


class FailureEnvelope(EnvelopeBase):
    """Reports a stage failure with recovery information."""

    envelope_kind: EnvelopeKind = EnvelopeKind.FAILURE
    error_code: str
    error_message: str
    failed_stage_id: str
    recoverable: bool = False


class ResponseEnvelope(EnvelopeBase):
    """Responds to a ClarificationEnvelope or other request."""

    envelope_kind: EnvelopeKind = EnvelopeKind.RESPONSE
    in_reply_to: str  # envelope_id being responded to
    response_payload: dict[str, Any] = {}


# Registry for deserialization by envelope_kind
ENVELOPE_TYPE_MAP: dict[EnvelopeKind, type[EnvelopeBase]] = {
    EnvelopeKind.WORK_ORDER: WorkOrderEnvelope,
    EnvelopeKind.EVENT: EventEnvelope,
    EnvelopeKind.ARTIFACT: ArtifactEnvelope,
    EnvelopeKind.CLARIFICATION: ClarificationEnvelope,
    EnvelopeKind.FAILURE: FailureEnvelope,
    EnvelopeKind.RESPONSE: ResponseEnvelope,
}
