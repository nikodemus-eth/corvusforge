"""Crypto bridge — three-tier signing with saoe-core, PyNaCl, or fail-closed.

Bridge boundary
---------------
Priority chain for cryptographic operations:

1. **saoe-core** (``saoe_core.crypto.keyring.Keyring``): Full SATL-compatible
   Ed25519 signing with key management.  Used when ``saoe-core`` is installed.

2. **PyNaCl** (``nacl.signing``): Native Ed25519 signing via libsodium.
   Produces real, verifiable signatures.  Used when PyNaCl is installed
   but saoe-core is not.

3. **Fail-closed**: No real crypto available.  ``generate_keypair()`` and
   ``sign_data()`` return deterministic stubs.  ``verify_data()`` **always
   returns False** — the system refuses to trust anything it cannot verify.

A warning is emitted once at import time indicating which tier is active.

v0.4.0: Added PyNaCl middle tier (Phase 1).
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier 1: Try-import saoe_core.crypto.keyring
# ---------------------------------------------------------------------------

_SAOE_CRYPTO_AVAILABLE: bool = False
_Keyring: Any = None

try:
    from saoe_core.crypto.keyring import Keyring as _Keyring  # type: ignore[import-untyped]

    _SAOE_CRYPTO_AVAILABLE = True
    logger.debug("saoe_core.crypto.keyring loaded — using SAOE crypto backend.")
except ImportError:
    pass  # Fall through to Tier 2

# ---------------------------------------------------------------------------
# Tier 2: Try-import PyNaCl (nacl.signing)
# ---------------------------------------------------------------------------

_NATIVE_CRYPTO_AVAILABLE: bool = False

if not _SAOE_CRYPTO_AVAILABLE:
    try:
        import nacl.signing  # noqa: F401 — availability check; used via local imports

        _NATIVE_CRYPTO_AVAILABLE = True
        logger.info(
            "PyNaCl (libsodium) loaded — using native Ed25519 crypto backend."
        )
    except ImportError:
        logger.warning(
            "Neither saoe-core nor PyNaCl found — crypto_bridge will use "
            "fail-closed stubs.  Install PyNaCl for real signing."
        )


# ---------------------------------------------------------------------------
# Public availability checks
# ---------------------------------------------------------------------------


def is_saoe_crypto_available() -> bool:
    """Return ``True`` if the saoe-core crypto backend is loaded."""
    return _SAOE_CRYPTO_AVAILABLE


def is_native_crypto_available() -> bool:
    """Return ``True`` if PyNaCl (libsodium) Ed25519 crypto is loaded."""
    return _NATIVE_CRYPTO_AVAILABLE


# ---------------------------------------------------------------------------
# Fail-closed helpers (Tier 3 — used only when neither backend is present)
# ---------------------------------------------------------------------------


def _failclosed_hash_pin(pin: str, *, salt: bytes | None = None) -> str:
    """Salted SHA-256 of *pin*.  Safe for non-production use."""
    if salt is None:
        salt = os.urandom(16)
    digest = hashlib.sha256(salt + pin.encode("utf-8")).hexdigest()
    return f"{salt.hex()}:{digest}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_keypair() -> tuple[str, str]:
    """Generate a signing key-pair.

    Returns
    -------
    tuple[str, str]
        ``(private_key_hex, public_key_hex)``

    Tier 1 (saoe-core): Real Ed25519 pair via Keyring.
    Tier 2 (PyNaCl): Real Ed25519 pair via nacl.signing.SigningKey.
    Tier 3 (fail-closed): Deterministic placeholder tuple.
    """
    # Tier 1: saoe-core
    if _SAOE_CRYPTO_AVAILABLE and _Keyring is not None:
        kr = _Keyring()
        return kr.generate_keypair()

    # Tier 2: PyNaCl
    if _NATIVE_CRYPTO_AVAILABLE:
        import nacl.signing

        sk = nacl.signing.SigningKey.generate()
        priv_hex = sk.encode().hex()
        pub_hex = sk.verify_key.encode().hex()
        return (priv_hex, pub_hex)

    # Tier 3: fail-closed stub
    logger.debug("generate_keypair: returning fail-closed stub key-pair.")
    priv = hashlib.sha256(b"corvusforge-stub-private").hexdigest()
    return (priv, "cf-stub-pubkey-no-saoe")


def sign_data(data: bytes, private_key: str) -> str:
    """Sign *data* with *private_key* and return the hex-encoded signature.

    Parameters
    ----------
    data:
        Raw bytes to sign (typically canonical JSON of an envelope).
    private_key:
        Hex-encoded private key (seed) returned by ``generate_keypair()``.

    Returns
    -------
    str
        Hex-encoded signature (128 hex chars = 64 bytes for Ed25519).
    """
    # Tier 1: saoe-core
    if _SAOE_CRYPTO_AVAILABLE and _Keyring is not None:
        kr = _Keyring()
        return kr.sign(data, private_key)

    # Tier 2: PyNaCl
    if _NATIVE_CRYPTO_AVAILABLE:
        import nacl.signing

        sk = nacl.signing.SigningKey(bytes.fromhex(private_key))
        signed = sk.sign(data)
        return signed.signature.hex()

    # Tier 3: fail-closed — HMAC stub (not verifiable)
    import hmac

    logger.debug("sign_data: using HMAC-SHA256 fail-closed stub (dev only).")
    return hmac.new(
        b"corvusforge-dev-only-do-not-use-in-production",
        data,
        hashlib.sha256,
    ).hexdigest()


def verify_data(data: bytes, signature: str, public_key: str) -> bool:
    """Verify that *signature* is valid for *data* under *public_key*.

    Parameters
    ----------
    data:
        The original bytes that were signed.
    signature:
        Hex-encoded signature produced by ``sign_data()``.
    public_key:
        Hex-encoded public key returned by ``generate_keypair()``.

    Returns
    -------
    bool
        ``True`` if the signature is valid, ``False`` otherwise.

    Fail-closed: returns ``False`` if no crypto backend is available,
    if the signature is empty/malformed, or if verification fails.
    """
    # Tier 1: saoe-core
    if _SAOE_CRYPTO_AVAILABLE and _Keyring is not None:
        kr = _Keyring()
        return kr.verify(data, signature, public_key)

    # Tier 2: PyNaCl
    if _NATIVE_CRYPTO_AVAILABLE:
        import nacl.signing
        from nacl.exceptions import BadSignatureError

        if not signature:
            return False
        try:
            sig_bytes = bytes.fromhex(signature)
            pub_bytes = bytes.fromhex(public_key)
            vk = nacl.signing.VerifyKey(pub_bytes)
            vk.verify(data, sig_bytes)
            return True
        except (BadSignatureError, ValueError, Exception):
            # BadSignatureError: cryptographic mismatch
            # ValueError: malformed hex / wrong byte length
            # Exception: any other unexpected error — fail closed
            return False

    # Tier 3: fail-closed
    logger.warning(
        "verify_data: no crypto backend available — cannot verify signature."
    )
    return False


def hash_pin(pin: str, *, salt: bytes | None = None) -> str:
    """Produce a salted hash of a human-entered PIN or passphrase.

    Parameters
    ----------
    pin:
        The cleartext PIN / passphrase.
    salt:
        Optional explicit salt (16 bytes).  If ``None`` a random salt is
        generated.

    Returns
    -------
    str
        Format ``"<salt_hex>:<digest_hex>"``.

    Note: hash_pin uses salted SHA-256 across all tiers.  This is appropriate
    for PINs / passphrases.  Ed25519 signing is not applicable here.
    """
    # Tier 1: saoe-core (may have its own format)
    if _SAOE_CRYPTO_AVAILABLE and _Keyring is not None:
        kr = _Keyring()
        return kr.hash_pin(pin, salt=salt)

    # Tiers 2 & 3: salted SHA-256 (same implementation)
    return _failclosed_hash_pin(pin, salt=salt)


def key_fingerprint(public_key: str) -> str:
    """Compute a short fingerprint of a public key.

    Returns the first 16 hex characters of SHA-256(public_key_bytes).
    Used for recording which trust root was active at a given point,
    without embedding the full key in ledger entries.
    """
    if not public_key:
        return ""
    digest = hashlib.sha256(public_key.encode("utf-8")).hexdigest()
    return digest[:16]


def compute_trust_context(
    *,
    plugin_trust_root: str = "",
    waiver_signing_key: str = "",
    anchor_key: str = "",
) -> dict[str, str]:
    """Build a trust context dict with fingerprints of active keys.

    The trust context is recorded in every ledger entry so that forensic
    analysis can determine which trust roots were active when the entry
    was written.  If a key is rotated, the fingerprint change is visible
    in the ledger.

    Parameters
    ----------
    plugin_trust_root:
        Public key used for plugin verification.
    waiver_signing_key:
        Public key used for waiver signature verification.
    anchor_key:
        Public key used for anchor signing (future).

    Returns
    -------
    dict[str, str]
        Keys: ``plugin_trust_root_fp``, ``waiver_signing_key_fp``,
        ``anchor_key_fp``.  Empty string if no key is configured.
    """
    return {
        "plugin_trust_root_fp": key_fingerprint(plugin_trust_root),
        "waiver_signing_key_fp": key_fingerprint(waiver_signing_key),
        "anchor_key_fp": key_fingerprint(anchor_key),
    }
