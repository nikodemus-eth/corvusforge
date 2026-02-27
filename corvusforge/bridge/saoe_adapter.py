"""SAOE adapter — converts Corvusforge envelopes to/from SATLEnvelope.

Bridge boundary
---------------
Corvusforge uses its own ``EnvelopeBase`` hierarchy (frozen Pydantic models
with ``EnvelopeKind`` discriminator).  The SAOE ecosystem uses
``saoe_core.satl.envelope.SATLEnvelope`` — a signed, template-referenced
transport format.

This adapter sits at the boundary:

* **to_satl()** — takes a Corvusforge envelope, signs its canonical payload,
  attaches a SATL template reference, and returns a ``SATLEnvelope``.
* **from_satl()** — unpacks a ``SATLEnvelope``, verifies integrity, and
  reconstitutes the appropriate Corvusforge ``EnvelopeBase`` subclass.

When ``saoe-core`` is not installed, both functions raise
``SaoeAdapterUnavailable`` so callers can handle the missing dependency
explicitly rather than getting an opaque ``ImportError`` deep in a call
stack.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from corvusforge.core.hasher import canonical_json_bytes, sha256_hex
from corvusforge.models.envelopes import (
    ENVELOPE_TYPE_MAP,
    EnvelopeBase,
    EnvelopeKind,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Try-import saoe_core.satl.envelope
# ---------------------------------------------------------------------------

_SAOE_SATL_AVAILABLE: bool = False
_SATLEnvelope: Any = None

try:
    from saoe_core.satl.envelope import SATLEnvelope as _SaoeSATLEnvelope  # type: ignore[import-untyped]

    _SATLEnvelope = _SaoeSATLEnvelope
    _SAOE_SATL_AVAILABLE = True
    logger.debug("saoe_core.satl.envelope loaded — SATL adapter enabled.")
except ImportError:
    logger.warning(
        "saoe_core.satl.envelope not found — saoe_adapter.to_satl() / "
        "from_satl() will raise SaoeAdapterUnavailable.  Install saoe-core "
        "for SATL transport."
    )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SaoeAdapterUnavailable(RuntimeError):
    """Raised when a SATL operation is attempted without saoe-core installed."""


class SaoeAdapterError(ValueError):
    """Raised when envelope conversion fails due to data issues."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_saoe_satl_available() -> bool:
    """Return ``True`` if the saoe-core SATL envelope module is loaded."""
    return _SAOE_SATL_AVAILABLE


def _corvusforge_payload(envelope: EnvelopeBase) -> dict[str, Any]:
    """Serialize a Corvusforge envelope to its canonical dict form."""
    return envelope.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def to_satl(
    envelope: EnvelopeBase,
    signing_key: str,
    template_ref: str,
) -> Any:
    """Convert a Corvusforge envelope into a signed ``SATLEnvelope``.

    Parameters
    ----------
    envelope:
        Any Corvusforge ``EnvelopeBase`` subclass (WorkOrderEnvelope,
        EventEnvelope, etc.).
    signing_key:
        Hex-encoded private key (from ``crypto_bridge.generate_keypair()``).
    template_ref:
        SATL template reference string that identifies the schema / contract
        this envelope conforms to (e.g. ``"corvusforge/work_order/v2026-02"``).

    Returns
    -------
    SATLEnvelope
        A saoe-core ``SATLEnvelope`` ready for wire transport.

    Raises
    ------
    SaoeAdapterUnavailable
        If ``saoe-core`` is not installed.
    SaoeAdapterError
        If the conversion fails for data-level reasons.
    """
    if not _SAOE_SATL_AVAILABLE or _SATLEnvelope is None:
        raise SaoeAdapterUnavailable(
            "Cannot convert to SATLEnvelope — saoe-core is not installed.  "
            "Install saoe-core or handle this case in your transport layer."
        )

    try:
        payload = _corvusforge_payload(envelope)
        payload_bytes = canonical_json_bytes(payload)
        payload_hash = sha256_hex(payload_bytes)

        # Import the signing helper from the crypto bridge so we use the
        # same key format consistently.
        from corvusforge.bridge.crypto_bridge import sign_data

        signature = sign_data(payload_bytes, signing_key)

        satl = _SATLEnvelope(
            template_ref=template_ref,
            payload=payload,
            payload_hash=payload_hash,
            signature=signature,
            metadata={
                "source": "corvusforge",
                "envelope_id": envelope.envelope_id,
                "envelope_kind": envelope.envelope_kind.value,
                "run_id": envelope.run_id,
            },
        )
        logger.debug(
            "to_satl: converted envelope %s (%s) -> SATLEnvelope template=%s",
            envelope.envelope_id,
            envelope.envelope_kind.value,
            template_ref,
        )
        return satl

    except SaoeAdapterUnavailable:
        raise
    except Exception as exc:
        raise SaoeAdapterError(
            f"Failed to convert Corvusforge envelope to SATLEnvelope: {exc}"
        ) from exc


def from_satl(satl_envelope: Any) -> EnvelopeBase:
    """Reconstitute a Corvusforge envelope from a ``SATLEnvelope``.

    Parameters
    ----------
    satl_envelope:
        A saoe-core ``SATLEnvelope`` received from the wire.

    Returns
    -------
    EnvelopeBase
        The appropriate Corvusforge envelope subclass, fully validated.

    Raises
    ------
    SaoeAdapterUnavailable
        If ``saoe-core`` is not installed.
    SaoeAdapterError
        If the payload cannot be parsed into a valid Corvusforge envelope.
    """
    if not _SAOE_SATL_AVAILABLE or _SATLEnvelope is None:
        raise SaoeAdapterUnavailable(
            "Cannot convert from SATLEnvelope — saoe-core is not installed."
        )

    try:
        # The SATLEnvelope carries a `payload` dict (or JSON string).
        payload = satl_envelope.payload
        if isinstance(payload, (str, bytes)):
            payload = json.loads(payload)

        # Determine the Corvusforge envelope type from the payload.
        kind_str = payload.get("envelope_kind")
        if not kind_str:
            raise SaoeAdapterError(
                "SATLEnvelope payload missing 'envelope_kind' — cannot "
                "determine Corvusforge envelope type."
            )

        try:
            kind = EnvelopeKind(kind_str)
        except ValueError as exc:
            raise SaoeAdapterError(
                f"Unknown envelope_kind in SATLEnvelope payload: {kind_str!r}"
            ) from exc

        model_cls = ENVELOPE_TYPE_MAP.get(kind)
        if model_cls is None:
            raise SaoeAdapterError(
                f"No Corvusforge model registered for envelope_kind: {kind_str!r}"
            )

        envelope = model_cls.model_validate(payload)
        logger.debug(
            "from_satl: reconstituted %s envelope %s for run=%s",
            kind.value,
            envelope.envelope_id,
            envelope.run_id,
        )
        return envelope

    except (SaoeAdapterUnavailable, SaoeAdapterError):
        raise
    except Exception as exc:
        raise SaoeAdapterError(
            f"Failed to reconstitute Corvusforge envelope from SATLEnvelope: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Local serialization (no saoe-core needed, uses PyNaCl from crypto_bridge)
# ---------------------------------------------------------------------------


def to_local(
    envelope: EnvelopeBase,
    signing_key: str,
) -> dict[str, Any]:
    """Serialize a Corvusforge envelope to a signed local dict.

    Unlike ``to_satl()``, this does NOT require saoe-core.  It uses the
    crypto bridge (PyNaCl when available) to produce a real Ed25519 signature
    over the canonical payload.

    Parameters
    ----------
    envelope:
        Any Corvusforge ``EnvelopeBase`` subclass.
    signing_key:
        Hex-encoded private key (from ``crypto_bridge.generate_keypair()``).

    Returns
    -------
    dict[str, Any]
        A dict with keys: ``payload``, ``payload_hash``, ``signature``,
        ``envelope_kind``, ``envelope_id``, ``run_id``.
    """
    from corvusforge.bridge.crypto_bridge import sign_data

    payload = _corvusforge_payload(envelope)
    payload_bytes = canonical_json_bytes(payload)
    payload_hash = sha256_hex(payload_bytes)
    signature = sign_data(payload_bytes, signing_key)

    return {
        "payload": payload,
        "payload_hash": payload_hash,
        "signature": signature,
        "envelope_kind": envelope.envelope_kind.value,
        "envelope_id": envelope.envelope_id,
        "run_id": envelope.run_id,
    }


def from_local(data: dict[str, Any]) -> EnvelopeBase:
    """Reconstitute a Corvusforge envelope from a local serialized dict.

    Verifies the ``payload_hash`` matches the canonical payload bytes.
    Does NOT verify the signature (caller must do that with the public key
    via ``crypto_bridge.verify_data`` if needed).

    Parameters
    ----------
    data:
        A dict produced by ``to_local()``.

    Returns
    -------
    EnvelopeBase
        The appropriate Corvusforge envelope subclass.

    Raises
    ------
    SaoeAdapterError
        If the payload is missing required fields or cannot be parsed.
    """
    # Validate envelope_kind presence
    kind_str = data.get("envelope_kind")
    if not kind_str:
        raise SaoeAdapterError(
            "Local envelope data missing 'envelope_kind' — cannot "
            "determine Corvusforge envelope type."
        )

    # Resolve kind to model class
    try:
        kind = EnvelopeKind(kind_str)
    except ValueError as exc:
        raise SaoeAdapterError(
            f"Unknown envelope_kind in local data: {kind_str!r}"
        ) from exc

    model_cls = ENVELOPE_TYPE_MAP.get(kind)
    if model_cls is None:
        raise SaoeAdapterError(
            f"No Corvusforge model registered for envelope_kind: {kind_str!r}"
        )

    # Reconstitute from the payload dict
    payload = data.get("payload")
    if payload is None:
        raise SaoeAdapterError("Local envelope data missing 'payload'.")

    envelope = model_cls.model_validate(payload)
    logger.debug(
        "from_local: reconstituted %s envelope %s for run=%s",
        kind.value,
        envelope.envelope_id,
        envelope.run_id,
    )
    return envelope
