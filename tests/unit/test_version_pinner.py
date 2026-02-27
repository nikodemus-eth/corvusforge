"""Tests for VersionPinner — pin recording, drift detection."""

from __future__ import annotations

import pytest

from corvusforge.core.version_pinner import VersionPinner, VersionDriftError
from corvusforge.models.versioning import VersionPin


class TestVersionPinner:
    def test_default_pin(self):
        pinner = VersionPinner()
        assert pinner.current_pin.pipeline_version == "0.1.0"

    def test_environment_hash_deterministic(self):
        pinner = VersionPinner()
        h1 = pinner.environment_hash({"KEY": "value"})
        h2 = pinner.environment_hash({"KEY": "value"})
        assert h1 == h2

    def test_environment_hash_changes_with_env(self):
        pinner = VersionPinner()
        h1 = pinner.environment_hash({"KEY": "a"})
        h2 = pinner.environment_hash({"KEY": "b"})
        assert h1 != h2

    def test_no_drift(self):
        pin = VersionPin()
        pinner = VersionPinner(pin)
        drifts = pinner.check_drift(pin, strict=False)
        assert drifts == []

    def test_drift_detected(self):
        current = VersionPin(pipeline_version="0.1.0")
        recorded = VersionPin(pipeline_version="0.0.9")
        pinner = VersionPinner(current)
        drifts = pinner.check_drift(recorded, strict=False)
        assert len(drifts) == 1
        assert "pipeline_version" in drifts[0]

    def test_strict_drift_raises(self):
        current = VersionPin(pipeline_version="0.1.0")
        recorded = VersionPin(pipeline_version="0.0.9")
        pinner = VersionPinner(current)
        with pytest.raises(VersionDriftError):
            pinner.check_drift(recorded, strict=True)
