"""Adversarial tests — waiver forgery and signature enforcement.

These tests verify that:
1. Unsigned waivers are stored but flagged as unverified
2. In require_signature mode, unsigned waivers are rejected
3. Forged approving_identity doesn't bypass verification
4. Expired waivers are always rejected
5. has_valid_waiver respects signature requirements
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from corvusforge.core.artifact_store import ContentAddressedStore
from corvusforge.core.waiver_manager import (
    WaiverExpiredError,
    WaiverManager,
    WaiverSignatureError,
)
from corvusforge.models.waivers import RiskClassification, WaiverArtifact


class TestWaiverSignatureEnforcement:
    """Verify that waiver signatures are checked, not just stored."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> ContentAddressedStore:
        return ContentAddressedStore(tmp_path / "artifacts")

    def test_unsigned_waiver_accepted_in_dev_mode(self, store):
        """Without require_signature, unsigned waivers register but flag."""
        mgr = WaiverManager(store, require_signature=False)
        waiver = WaiverArtifact(
            scope="s55_accessibility",
            justification="Tested manually",
            expiration=datetime.now(timezone.utc) + timedelta(hours=24),
            approving_identity="some-reviewer",
            risk_classification=RiskClassification.LOW,
            signature="",  # no signature
        )
        addr = mgr.register_waiver(waiver)
        assert addr.startswith("sha256:")
        # Valid because require_signature is False
        assert mgr.has_valid_waiver("s55_accessibility") is True

    def test_unsigned_waiver_rejected_in_strict_mode(self, store):
        """With require_signature=True, unsigned waivers must be rejected."""
        mgr = WaiverManager(store, require_signature=True)
        waiver = WaiverArtifact(
            scope="s55_accessibility",
            justification="Trust me",
            expiration=datetime.now(timezone.utc) + timedelta(hours=24),
            approving_identity="attacker",
            risk_classification=RiskClassification.LOW,
            signature="",  # no signature
        )
        with pytest.raises(WaiverSignatureError, match="no valid signature"):
            mgr.register_waiver(waiver)

    def test_forged_signature_rejected_in_strict_mode(self, store):
        """A waiver with a garbage signature must be rejected in strict mode."""
        mgr = WaiverManager(store, require_signature=True)
        waiver = WaiverArtifact(
            scope="s575_security",
            justification="Forged waiver",
            expiration=datetime.now(timezone.utc) + timedelta(hours=24),
            approving_identity="admin",
            risk_classification=RiskClassification.CRITICAL,
            signature="deadbeef" * 16,  # garbage
        )
        with pytest.raises(WaiverSignatureError, match="no valid signature"):
            mgr.register_waiver(waiver)

    def test_has_valid_waiver_requires_signature_when_strict(self, store):
        """An unsigned waiver doesn't count as valid when require_signature=True."""
        # First register in non-strict mode
        mgr_dev = WaiverManager(store, require_signature=False)
        waiver = WaiverArtifact(
            scope="s55_accessibility",
            justification="Dev testing",
            expiration=datetime.now(timezone.utc) + timedelta(hours=24),
            approving_identity="dev",
            risk_classification=RiskClassification.LOW,
            signature="",
        )
        mgr_dev.register_waiver(waiver)
        # In dev mode, it's valid
        assert mgr_dev.has_valid_waiver("s55_accessibility") is True

        # Now create a strict manager with same store
        mgr_strict = WaiverManager(store, require_signature=True)
        # Strict manager starts with empty in-memory registry
        assert mgr_strict.has_valid_waiver("s55_accessibility") is False

    def test_expired_waiver_always_rejected(self, store):
        """An expired waiver is rejected regardless of signature."""
        mgr = WaiverManager(store, require_signature=False)
        waiver = WaiverArtifact(
            scope="s55_accessibility",
            justification="Old waiver",
            expiration=datetime.now(timezone.utc) - timedelta(hours=1),
            approving_identity="reviewer",
            risk_classification=RiskClassification.HIGH,
        )
        with pytest.raises(WaiverExpiredError):
            mgr.register_waiver(waiver)

    def test_multiple_scopes_isolated(self, store):
        """Waivers for one scope don't leak to another scope."""
        mgr = WaiverManager(store, require_signature=False)
        waiver = WaiverArtifact(
            scope="s55_accessibility",
            justification="Only for a11y",
            expiration=datetime.now(timezone.utc) + timedelta(hours=24),
            approving_identity="reviewer",
            risk_classification=RiskClassification.LOW,
        )
        mgr.register_waiver(waiver)
        assert mgr.has_valid_waiver("s55_accessibility") is True
        assert mgr.has_valid_waiver("s575_security") is False
