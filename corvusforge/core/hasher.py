"""Canonical hashing helpers for replay, idempotency, and content addressing.

Uses the same canonical JSON serialization as saoe_core.satl.envelope to
ensure hash compatibility across the SAOE and Corvusforge boundary.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from corvusforge.models.versioning import VersionPin


def canonical_json_bytes(obj: Any) -> bytes:
    """Produce canonical JSON bytes — deterministic, sorted, compact.

    Matches saoe_core's canonical_bytes() so hashes are compatible:
    - sorted keys
    - no whitespace separators (",", ":")
    - ensure_ascii=True
    - UTF-8 encoding
    """
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """Return the SHA-256 hex digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def content_address(obj: Any) -> str:
    """Content-address a JSON-serializable object.

    Returns "sha256:<hex>" format used by the artifact store.
    """
    return f"sha256:{sha256_hex(canonical_json_bytes(obj))}"


def compute_input_hash(stage_id: str, inputs: dict[str, Any]) -> str:
    """SHA-256 of canonical(stage_id + sorted inputs).

    Used for replay detection: if inputs haven't changed,
    a replayed stage should produce the same output.
    """
    payload = {"stage_id": stage_id, "inputs": inputs}
    return sha256_hex(canonical_json_bytes(payload))


def compute_output_hash(stage_id: str, outputs: dict[str, Any]) -> str:
    """SHA-256 of canonical(stage_id + sorted outputs).

    Records what a stage produced for idempotency checks.
    """
    payload = {"stage_id": stage_id, "outputs": outputs}
    return sha256_hex(canonical_json_bytes(payload))


def compute_environment_snapshot_hash(
    version_pin: VersionPin, env_vars: dict[str, str] | None = None
) -> str:
    """SHA-256 of canonical(version_pin + sorted env_vars).

    Detects environment drift between original run and replay.
    """
    payload = {
        "version_pin": version_pin.model_dump(),
        "env_vars": env_vars or {},
    }
    return sha256_hex(canonical_json_bytes(payload))


def compute_entry_hash(entry_dict: dict[str, Any]) -> str:
    """SHA-256 of a ledger entry (excluding the entry_hash field itself).

    This is the seal that makes each entry tamper-evident.
    """
    # Remove entry_hash before hashing (it's the field we're computing)
    d = {k: v for k, v in entry_dict.items() if k != "entry_hash"}
    return sha256_hex(canonical_json_bytes(d))
