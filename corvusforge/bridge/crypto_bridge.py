"""Crypto bridge — wraps saoe_core.crypto.keyring for Corvusforge signing.

Bridge boundary
---------------
When ``saoe-core`` is installed, this module delegates to its ``Keyring``
implementation, which manages Ed25519 key-pairs and produces SATL-compatible
signatures.

When ``saoe-core`` is *not* installed, every function degrades gracefully:

* ``generate_keypair()``  returns a deterministic placeholder tuple.
* ``sign_data()``         returns a SHA-256 HMAC using a local fallback key.
* ``verify_data()``       always returns ``False`` (no real verification
  possible without the real keyring).
* ``hash_pin()``          returns a salted SHA-256 digest (safe for
  non-production use; production deployments MUST use saoe-core).

A warning is emitted once at import time when the fallback path is taken so
operators can tell at a glance whether SAOE crypto is active.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Try-import saoe_core.crypto.keyring
# ---------------------------------------------------------------------------

_SAOE_CRYPTO_AVAILABLE: bool = False
_Keyring: Any = None

try:
    from saoe_core.crypto.keyring import Keyring as _SaoeKeyring  # type: ignore[import-untyped]

    _Keyring = _SaoeKeyring
    _SAOE_CRYPTO_AVAILABLE = True
    logger.debug("saoe_core.crypto.keyring loaded — using SAOE crypto backend.")
except ImportError:
    logger.warning(
        "saoe_core.crypto.keyring not found — crypto_bridge will use "
        "local fallback stubs.  Install saoe-core for production signing."
    )


def is_saoe_crypto_available() -> bool:
    """Return ``True`` if the saoe-core crypto backend is loaded."""
    return _SAOE_CRYPTO_AVAILABLE


# ---------------------------------------------------------------------------
# Fallback helpers (used only when saoe-core is absent)
# ---------------------------------------------------------------------------

_FALLBACK_SECRET = b"corvusforge-dev-only-do-not-use-in-production"

# A fixed placeholder "public key" so callers always get a tuple back.
_FALLBACK_PUBLIC_KEY = "cf-stub-pubkey-no-saoe"


def _fallback_sign(data: bytes) -> str:
    """HMAC-SHA256 using a static dev-only key.  NOT production-safe."""
    return hmac.new(_FALLBACK_SECRET, data, hashlib.sha256).hexdigest()


def _fallback_hash_pin(pin: str, *, salt: bytes | None = None) -> str:
    """Salted SHA-256 of *pin*.  Acceptable for dev; use saoe-core for prod."""
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

    When saoe-core is available the key-pair is a real Ed25519 pair managed
    by ``Keyring``.  Otherwise a placeholder tuple is returned.
    """
    if _SAOE_CRYPTO_AVAILABLE and _Keyring is not None:
        kr = _Keyring()
        return kr.generate_keypair()

    logger.debug("generate_keypair: returning fallback stub key-pair.")
    # Deterministic stub so callers can still exercise the API.
    priv = hashlib.sha256(b"corvusforge-stub-private").hexdigest()
    return (priv, _FALLBACK_PUBLIC_KEY)


def sign_data(data: bytes, private_key: str) -> str:
    """Sign *data* with *private_key* and return the hex-encoded signature.

    Parameters
    ----------
    data:
        Raw bytes to sign (typically canonical JSON of an envelope).
    private_key:
        Hex-encoded private key returned by ``generate_keypair()``.

    Returns
    -------
    str
        Hex-encoded signature.
    """
    if _SAOE_CRYPTO_AVAILABLE and _Keyring is not None:
        kr = _Keyring()
        return kr.sign(data, private_key)

    logger.debug("sign_data: using HMAC-SHA256 fallback (dev only).")
    return _fallback_sign(data)


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

    In fallback mode this **always returns False** because HMAC verification
    without the saoe-core keyring cannot guarantee authenticity.
    """
    if _SAOE_CRYPTO_AVAILABLE and _Keyring is not None:
        kr = _Keyring()
        return kr.verify(data, signature, public_key)

    logger.warning(
        "verify_data: saoe-core not available — cannot verify signature."
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
        Format ``"<salt_hex>:<digest_hex>"`` when using the fallback, or
        the saoe-core native format when available.
    """
    if _SAOE_CRYPTO_AVAILABLE and _Keyring is not None:
        kr = _Keyring()
        return kr.hash_pin(pin, salt=salt)

    return _fallback_hash_pin(pin, salt=salt)
