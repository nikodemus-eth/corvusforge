"""Tests for MonitorProjection — pure read-only view over the RunLedger.

Verifies that:
1. MonitorProjection re-derives state from ledger (no cached state).
2. Trust context health is surfaced in MonitorSnapshot.
3. Trust context version is reported.
4. Chain validity is checked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from corvusforge.config import ProdConfig
from corvusforge.core.orchestrator import Orchestrator
from corvusforge.core.run_ledger import RunLedger
from corvusforge.models.config import PipelineConfig
from corvusforge.models.stages import StageState
from corvusforge.monitor.projection import MonitorProjection

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pipeline_config(tmp_path: Path) -> PipelineConfig:
    return PipelineConfig(
        ledger_db_path=tmp_path / "ledger.db",
        artifact_store_path=tmp_path / "artifacts",
    )


@pytest.fixture
def ledger(pipeline_config: PipelineConfig) -> RunLedger:
    return RunLedger(pipeline_config.ledger_db_path)


# ---------------------------------------------------------------------------
# Test: Basic snapshot
# ---------------------------------------------------------------------------


class TestMonitorSnapshotBasic:
    """MonitorProjection produces correct snapshots."""

    def test_empty_run_produces_snapshot(self, ledger: RunLedger):
        """A run with no entries still produces a valid snapshot."""
        proj = MonitorProjection(ledger)
        snap = proj.snapshot("nonexistent-run")
        assert snap.run_id == "nonexistent-run"
        assert snap.total_stages > 0
        assert snap.completed_count == 0
        assert snap.chain_valid is True

    def test_snapshot_reflects_ledger_entries(
        self, pipeline_config: PipelineConfig, ledger: RunLedger
    ):
        """Snapshot must reflect the current ledger state."""
        orch = Orchestrator(config=pipeline_config)
        orch.start_run()

        proj = MonitorProjection(ledger)
        snap = proj.snapshot(orch.run_id)

        # s0_intake should be PASSED after start_run
        s0 = next(s for s in snap.stages if s.stage_id == "s0_intake")
        assert s0.state == StageState.PASSED


# ---------------------------------------------------------------------------
# Test: Trust context health in monitor
# ---------------------------------------------------------------------------


class TestMonitorTrustContextHealth:
    """Monitor must surface trust context health status."""

    def test_healthy_trust_context(
        self, pipeline_config: PipelineConfig, ledger: RunLedger
    ):
        """Run with all required keys configured is trust-healthy."""
        prod_config = ProdConfig(
            environment="development",
            plugin_trust_root="test-key-1",
            waiver_signing_key="test-key-2",
        )
        orch = Orchestrator(config=pipeline_config, prod_config=prod_config)
        orch.start_run()

        proj = MonitorProjection(ledger)
        snap = proj.snapshot(orch.run_id)

        assert snap.trust_context_healthy is True
        assert snap.trust_context_warnings == []

    def test_unhealthy_trust_context_missing_plugin_key(
        self, pipeline_config: PipelineConfig, ledger: RunLedger
    ):
        """Run without plugin trust root should be trust-unhealthy."""
        orch = Orchestrator(config=pipeline_config)  # no trust keys
        orch.start_run()

        proj = MonitorProjection(ledger)
        snap = proj.snapshot(orch.run_id)

        assert snap.trust_context_healthy is False
        assert len(snap.trust_context_warnings) >= 1

    def test_custom_required_keys_affect_health(
        self, pipeline_config: PipelineConfig, ledger: RunLedger
    ):
        """Custom required keys change what the monitor considers healthy."""
        # Configure only anchor_key but not plugin/waiver
        prod_config = ProdConfig(
            environment="development",
            anchor_key="test-anchor-key",
        )
        orch = Orchestrator(config=pipeline_config, prod_config=prod_config)
        orch.start_run()

        # Only require anchor_key — which IS configured
        proj = MonitorProjection(
            ledger,
            trust_context_required_keys=["anchor_key"],
        )
        snap = proj.snapshot(orch.run_id)

        assert snap.trust_context_healthy is True
        assert snap.trust_context_warnings == []

    def test_trust_context_version_in_snapshot(
        self, pipeline_config: PipelineConfig, ledger: RunLedger
    ):
        """Snapshot reports trust_context_version from latest entry."""
        orch = Orchestrator(config=pipeline_config)
        orch.start_run()

        proj = MonitorProjection(ledger)
        snap = proj.snapshot(orch.run_id)

        assert snap.trust_context_version == "1"

    def test_empty_run_defaults_trust_healthy(self, ledger: RunLedger):
        """A run with no entries defaults to trust-healthy."""
        proj = MonitorProjection(ledger)
        snap = proj.snapshot("no-such-run")
        assert snap.trust_context_healthy is True
        assert snap.trust_context_warnings == []
