"""Unit tests for the crypto bridge — real Ed25519 via PyNaCl.

Phase 1 of v0.4.0: Replace HMAC-SHA256 fallback stubs with real
Ed25519 signing and verification using PyNaCl (libsodium).

These tests exercise the PUBLIC API of crypto_bridge.py and assert
that the native crypto path produces correct, interoperable results.

TDD: RED phase — these tests define the desired behavior.
"""

from __future__ import annotations

import pytest

from corvusforge.bridge.crypto_bridge import (
    compute_trust_context,
    generate_keypair,
    hash_pin,
    is_saoe_crypto_available,
    key_fingerprint,
    sign_data,
    verify_data,
)


# ---------------------------------------------------------------------------
# Test: Key generation
# ---------------------------------------------------------------------------


class TestGenerateKeypair:
    """Ed25519 key generation must return valid hex-encoded key pairs."""

    def test_generate_keypair_returns_valid_ed25519_pair(self):
        """Private key = 64 hex chars (32 bytes), public key = 64 hex chars."""
        priv, pub = generate_keypair()

        # Ed25519 private key (seed) is 32 bytes = 64 hex chars
        assert len(priv) == 64, f"Private key hex length {len(priv)}, expected 64"
        # Ed25519 public key is 32 bytes = 64 hex chars
        assert len(pub) == 64, f"Public key hex length {len(pub)}, expected 64"

        # Both must be valid hex
        bytes.fromhex(priv)
        bytes.fromhex(pub)

    def test_generate_keypair_produces_unique_pairs(self):
        """Each call must produce a different key pair (random generation)."""
        priv1, pub1 = generate_keypair()
        priv2, pub2 = generate_keypair()

        assert priv1 != priv2, "Two generated private keys must differ"
        assert pub1 != pub2, "Two generated public keys must differ"


# ---------------------------------------------------------------------------
# Test: Signing
# ---------------------------------------------------------------------------


class TestSignData:
    """Ed25519 signing must produce deterministic, verifiable signatures."""

    def test_sign_data_produces_deterministic_signature(self):
        """Same data + same key must produce the same signature."""
        priv, _pub = generate_keypair()
        data = b"corvusforge-test-payload"

        sig1 = sign_data(data, priv)
        sig2 = sign_data(data, priv)

        assert sig1 == sig2, "Ed25519 signatures must be deterministic"

    def test_sign_data_returns_hex_string(self):
        """Signature must be a hex-encoded string of correct length."""
        priv, _pub = generate_keypair()
        sig = sign_data(b"test", priv)

        # Ed25519 signature is 64 bytes = 128 hex chars
        assert len(sig) == 128, f"Signature hex length {len(sig)}, expected 128"
        bytes.fromhex(sig)  # Must be valid hex


# ---------------------------------------------------------------------------
# Test: Verification round-trip
# ---------------------------------------------------------------------------


class TestVerifyData:
    """Ed25519 verification must correctly accept and reject signatures."""

    def test_verify_data_round_trip(self):
        """generate -> sign -> verify must return True."""
        priv, pub = generate_keypair()
        data = b"corvusforge-round-trip-test"

        sig = sign_data(data, priv)
        result = verify_data(data, sig, pub)

        assert result is True, "Valid signature must verify as True"

    def test_verify_data_wrong_key_returns_false(self):
        """Signature from key A must not verify under key B."""
        priv_a, _pub_a = generate_keypair()
        _priv_b, pub_b = generate_keypair()
        data = b"cross-key-test"

        sig = sign_data(data, priv_a)
        result = verify_data(data, sig, pub_b)

        assert result is False, "Wrong public key must reject signature"

    def test_verify_data_tampered_data_returns_false(self):
        """Signature must not verify if data is modified after signing."""
        priv, pub = generate_keypair()
        original = b"original-data"
        tampered = b"tampered-data"

        sig = sign_data(original, priv)
        result = verify_data(tampered, sig, pub)

        assert result is False, "Tampered data must reject signature"

    def test_verify_data_empty_signature_returns_false(self):
        """Empty signature string must return False, not raise."""
        priv, pub = generate_keypair()
        data = b"empty-sig-test"

        result = verify_data(data, "", pub)

        assert result is False, "Empty signature must return False"

    def test_verify_data_malformed_signature_returns_false(self):
        """Garbage signature must return False, not raise an exception."""
        priv, pub = generate_keypair()
        data = b"garbage-sig-test"

        result = verify_data(data, "AAAA_not_a_real_signature_ZZZZ", pub)

        assert result is False, "Malformed signature must return False"


# ---------------------------------------------------------------------------
# Test: Pin hashing
# ---------------------------------------------------------------------------


class TestHashPin:
    """Pin hashing uses salted SHA-256 and must be deterministic per salt."""

    def test_hash_pin_produces_salted_hash(self):
        """Output format must be 'salt_hex:digest_hex'."""
        result = hash_pin("1234")

        assert ":" in result, "hash_pin output must contain ':' separator"
        salt_hex, digest_hex = result.split(":", 1)
        # Salt is 16 bytes = 32 hex chars
        assert len(salt_hex) == 32, f"Salt hex length {len(salt_hex)}, expected 32"
        # SHA-256 digest is 32 bytes = 64 hex chars
        assert len(digest_hex) == 64, f"Digest hex length {len(digest_hex)}, expected 64"

    def test_hash_pin_different_salts_different_hashes(self):
        """Same PIN with different salts must produce different hashes."""
        result1 = hash_pin("1234", salt=b"\x00" * 16)
        result2 = hash_pin("1234", salt=b"\xff" * 16)

        assert result1 != result2, "Different salts must produce different hashes"

    def test_hash_pin_same_salt_same_hash(self):
        """Same PIN + same salt must produce identical output."""
        salt = b"\xab\xcd" * 8  # 16 bytes
        result1 = hash_pin("mypin", salt=salt)
        result2 = hash_pin("mypin", salt=salt)

        assert result1 == result2, "Same salt + same PIN must be deterministic"


# ---------------------------------------------------------------------------
# Test: Key fingerprinting and trust context
# ---------------------------------------------------------------------------


class TestKeyFingerprint:
    """Key fingerprints must be deterministic and truncated correctly."""

    def test_key_fingerprint_deterministic(self):
        """Same key must always produce the same fingerprint."""
        _priv, pub = generate_keypair()

        fp1 = key_fingerprint(pub)
        fp2 = key_fingerprint(pub)

        assert fp1 == fp2, "Fingerprint must be deterministic"
        assert len(fp1) == 16, f"Fingerprint length {len(fp1)}, expected 16"

    def test_key_fingerprint_empty_returns_empty(self):
        """Empty key must return empty fingerprint."""
        assert key_fingerprint("") == ""


class TestComputeTrustContext:
    """Trust context with real keys must produce real fingerprints."""

    def test_compute_trust_context_with_real_keys(self):
        """Generated keys must produce non-empty fingerprints in trust context."""
        _priv1, pub1 = generate_keypair()
        _priv2, pub2 = generate_keypair()

        ctx = compute_trust_context(
            plugin_trust_root=pub1,
            waiver_signing_key=pub2,
        )

        assert ctx["plugin_trust_root_fp"] != "", "plugin fingerprint must be non-empty"
        assert ctx["waiver_signing_key_fp"] != "", "waiver fingerprint must be non-empty"
        assert ctx["anchor_key_fp"] == "", "anchor fingerprint must be empty (not set)"

        # Fingerprints must be 16 hex chars
        assert len(ctx["plugin_trust_root_fp"]) == 16
        assert len(ctx["waiver_signing_key_fp"]) == 16


# ---------------------------------------------------------------------------
# Test: Availability flags
# ---------------------------------------------------------------------------


class TestCryptoAvailability:
    """Crypto availability flags must reflect installed backends."""

    def test_is_saoe_crypto_available_still_false(self):
        """saoe-core is not installed, so SAOE crypto must be unavailable."""
        assert is_saoe_crypto_available() is False

    def test_is_native_crypto_available_true(self):
        """PyNaCl is installed, so native crypto must be available."""
        from corvusforge.bridge.crypto_bridge import is_native_crypto_available

        assert is_native_crypto_available() is True
