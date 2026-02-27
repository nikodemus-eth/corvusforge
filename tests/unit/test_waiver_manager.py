"""Tests for WaiverManager — validation, storage, expiration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from corvusforge.core.waiver_manager import WaiverExpiredError, WaiverManager
from corvusforge.models.waivers import RiskClassification, WaiverArtifact


class TestWaiverManager:
    def _make_waiver(self, scope: str = "s55_accessibility", hours: int = 1) -> WaiverArtifact:
        return WaiverArtifact(
            scope=scope,
            justification="Test waiver for testing",
            expiration=datetime.now(timezone.utc) + timedelta(hours=hours),
            approving_identity="test-approver",
            risk_classification=RiskClassification.LOW,
        )

    def test_register_waiver(self, waiver_manager: WaiverManager):
        waiver = self._make_waiver()
        addr = waiver_manager.register_waiver(waiver)
        assert addr.startswith("sha256:")

    def test_has_valid_waiver(self, waiver_manager: WaiverManager):
        waiver = self._make_waiver()
        waiver_manager.register_waiver(waiver)
        assert waiver_manager.has_valid_waiver("s55_accessibility") is True
        assert waiver_manager.has_valid_waiver("nonexistent") is False

    def test_expired_waiver_rejected(self, waiver_manager: WaiverManager):
        waiver = self._make_waiver(hours=-1)
        with pytest.raises(WaiverExpiredError):
            waiver_manager.register_waiver(waiver)

    def test_get_active_waivers(self, waiver_manager: WaiverManager):
        waiver_manager.register_waiver(self._make_waiver())
        active = waiver_manager.get_active_waivers("s55_accessibility")
        assert len(active) == 1

    def test_get_all_active_waivers(self, waiver_manager: WaiverManager):
        waiver_manager.register_waiver(self._make_waiver("s55_accessibility"))
        waiver_manager.register_waiver(self._make_waiver("s575_security"))
        all_active = waiver_manager.get_all_active_waivers()
        assert len(all_active) == 2
