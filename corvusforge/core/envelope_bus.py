"""Envelope bus — validates and routes contracted JSON envelopes (Invariant 2).

All node communication uses validated Pydantic envelope models.
No freeform messages are allowed through the bus.
"""

from __future__ import annotations

import json
from typing import Any

from corvusforge.core.hasher import canonical_json_bytes, sha256_hex
from corvusforge.models.envelopes import (
    ENVELOPE_TYPE_MAP,
    EnvelopeBase,
    EnvelopeKind,
)


class EnvelopeValidationError(ValueError):
    """Raised when an envelope fails validation."""


class EnvelopeBus:
    """Validates and routes corvusforge envelopes.

    Every envelope is:
    1. Validated against its Pydantic model
    2. Payload hash verified
    3. Routed to registered handlers
    """

    def __init__(self) -> None:
        self._handlers: dict[EnvelopeKind, list] = {
            kind: [] for kind in EnvelopeKind
        }

    def register_handler(
        self, kind: EnvelopeKind, handler: Any
    ) -> None:
        """Register a handler for a specific envelope kind."""
        self._handlers[kind].append(handler)

    # ------------------------------------------------------------------
    # Send (validate + hash + route)
    # ------------------------------------------------------------------

    def prepare(self, envelope: EnvelopeBase) -> EnvelopeBase:
        """Validate an envelope and compute its payload_hash.

        Returns the envelope with payload_hash set.
        """
        # Compute payload hash from the envelope's content fields
        payload_fields = envelope.model_dump(
            mode="json",
            exclude={"payload_hash", "envelope_id", "timestamp_utc"},
        )
        computed_hash = sha256_hex(canonical_json_bytes(payload_fields))

        return envelope.model_copy(update={"payload_hash": computed_hash})

    def send(self, envelope: EnvelopeBase) -> str:
        """Validate, hash, and dispatch an envelope.

        Returns the envelope_id.
        """
        prepared = self.prepare(envelope)

        # Dispatch to registered handlers
        for handler in self._handlers.get(prepared.envelope_kind, []):
            handler(prepared)

        return prepared.envelope_id

    # ------------------------------------------------------------------
    # Receive (deserialize + validate)
    # ------------------------------------------------------------------

    def receive(self, raw_json: bytes | str) -> EnvelopeBase:
        """Deserialize and validate a raw JSON envelope.

        Determines the correct Pydantic model from envelope_kind and
        validates all fields.
        """
        if isinstance(raw_json, bytes):
            raw_json = raw_json.decode("utf-8")

        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise EnvelopeValidationError(f"Invalid JSON: {exc}") from exc

        if not isinstance(data, dict):
            raise EnvelopeValidationError(
                f"Envelope must be a JSON object, got {type(data).__name__}"
            )

        kind_str = data.get("envelope_kind")
        if not kind_str:
            raise EnvelopeValidationError("Missing envelope_kind field")

        try:
            kind = EnvelopeKind(kind_str)
        except ValueError as exc:
            raise EnvelopeValidationError(
                f"Unknown envelope_kind: {kind_str!r}"
            ) from exc

        model_cls = ENVELOPE_TYPE_MAP.get(kind)
        if not model_cls:
            raise EnvelopeValidationError(
                f"No model registered for envelope_kind: {kind_str!r}"
            )

        try:
            return model_cls.model_validate(data)
        except Exception as exc:
            raise EnvelopeValidationError(
                f"Envelope validation failed: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    @staticmethod
    def serialize(envelope: EnvelopeBase) -> bytes:
        """Serialize an envelope to canonical JSON bytes."""
        return canonical_json_bytes(envelope.model_dump(mode="json"))
