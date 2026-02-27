"""End-to-end integration tests — full pipeline execution through Stage 0→7.

These tests exercise the Orchestrator, StageMachine, RunLedger, PrerequisiteGraph,
ArtifactStore, WaiverManager, and VersionPinner working together.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from corvusforge.core.artifact_store import ContentAddressedStore
from corvusforge.core.orchestrator import Orchestrator
from corvusforge.core.waiver_manager import WaiverExpiredError, WaiverManager
from corvusforge.models.config import PipelineConfig
from corvusforge.models.stages import StageState
from corvusforge.models.waivers import RiskClassification, WaiverArtifact
from corvusforge.monitor.projection import MonitorProjection


class TestFullPipeline:
    """End-to-end pipeline execution: start → execute stages → verify."""

    @pytest.fixture
    def orch(self, tmp_path: Path) -> Orchestrator:
        config = PipelineConfig(
            ledger_db_path=tmp_path / "ledger.db",
            artifact_store_path=tmp_path / "artifacts",
        )
        return Orchestrator(config=config)

    def test_start_run_creates_config(self, orch: Orchestrator):
        rc = orch.start_run()
        assert rc.run_id == orch.run_id
        assert rc.run_id.startswith("cf-")

    def test_start_run_initializes_all_stages(self, orch: Orchestrator):
        orch.start_run()
        states = orch.get_states()
        # s0 should be PASSED (auto-completed during start_run)
        assert states["s0_intake"] == StageState.PASSED
        # Everything else should be NOT_STARTED
        for stage_id, state in states.items():
            if stage_id != "s0_intake":
                assert state == StageState.NOT_STARTED, f"{stage_id} should be NOT_STARTED"

    def test_execute_stages_sequentially(self, orch: Orchestrator):
        orch.start_run()

        # Execute s1 through s4 (no prerequisites beyond s0)
        for stage_id in ["s1_prerequisites", "s2_environment", "s3_test_contract", "s4_code_plan"]:
            orch.execute_stage(stage_id)
            assert orch.get_stage_state(stage_id) == StageState.PASSED

    def test_execute_s5_implementation(self, orch: Orchestrator):
        orch.start_run()
        # Walk through prerequisites
        for sid in ["s1_prerequisites", "s2_environment", "s3_test_contract", "s4_code_plan"]:
            orch.execute_stage(sid)

        orch.execute_stage("s5_implementation")
        assert orch.get_stage_state("s5_implementation") == StageState.PASSED

    def test_gate_stages_require_prerequisites(self, orch: Orchestrator):
        """s6_verification requires both s55 and s575 to pass."""
        orch.start_run()
        # Walk through s0→s5
        for sid in ["s1_prerequisites", "s2_environment", "s3_test_contract",
                     "s4_code_plan", "s5_implementation"]:
            orch.execute_stage(sid)

        # Execute both gate stages
        orch.execute_stage("s55_accessibility")
        orch.execute_stage("s575_security")

        # Now s6 should be executable
        orch.execute_stage("s6_verification")
        assert orch.get_stage_state("s6_verification") == StageState.PASSED

    def test_full_pipeline_s0_to_s7(self, orch: Orchestrator):
        """Complete pipeline run from intake to release."""
        orch.start_run()

        stage_order = [
            "s1_prerequisites", "s2_environment", "s3_test_contract",
            "s4_code_plan", "s5_implementation",
            "s55_accessibility", "s575_security",
            "s6_verification", "s7_release",
        ]
        for stage_id in stage_order:
            orch.execute_stage(stage_id)

        # All stages should be PASSED
        states = orch.get_states()
        for stage_id, state in states.items():
            assert state == StageState.PASSED, f"{stage_id} = {state}, expected PASSED"

    def test_ledger_chain_valid_after_full_run(self, orch: Orchestrator):
        orch.start_run()
        for sid in ["s1_prerequisites", "s2_environment", "s3_test_contract",
                     "s4_code_plan", "s5_implementation",
                     "s55_accessibility", "s575_security",
                     "s6_verification", "s7_release"]:
            orch.execute_stage(sid)

        assert orch.verify_chain() is True

    def test_ledger_entries_recorded(self, orch: Orchestrator):
        orch.start_run()
        orch.execute_stage("s1_prerequisites")

        entries = orch.get_run_entries()
        # Should have: s0 start, s0 pass, s1 init, s1 start, s1 pass (at minimum)
        assert len(entries) >= 4

    def test_resume_run(self, tmp_path: Path):
        config = PipelineConfig(
            ledger_db_path=tmp_path / "ledger.db",
            artifact_store_path=tmp_path / "artifacts",
        )
        # First run: start and execute some stages
        orch1 = Orchestrator(config=config)
        orch1.start_run()
        orch1.execute_stage("s1_prerequisites")
        run_id = orch1.run_id

        # Resume
        orch2 = Orchestrator(config=config, run_id=run_id)
        states = orch2.resume_run(run_id)
        assert states["s0_intake"] == StageState.PASSED
        assert states["s1_prerequisites"] == StageState.PASSED

        # Can continue execution
        orch2.execute_stage("s2_environment")
        assert orch2.get_stage_state("s2_environment") == StageState.PASSED


class TestMonitorProjectionIntegration:
    """Test Build Monitor projection against a live pipeline."""

    @pytest.fixture
    def pipeline(self, tmp_path: Path):
        config = PipelineConfig(
            ledger_db_path=tmp_path / "ledger.db",
            artifact_store_path=tmp_path / "artifacts",
        )
        orch = Orchestrator(config=config)
        orch.start_run()
        return orch

    def test_snapshot_reflects_pipeline_state(self, pipeline: Orchestrator):
        projection = MonitorProjection(pipeline.ledger)
        snapshot = projection.snapshot(pipeline.run_id)

        assert snapshot.run_id == pipeline.run_id
        assert snapshot.total_stages == 10
        assert snapshot.completed_count == 1  # s0 is PASSED

    def test_snapshot_updates_after_execution(self, pipeline: Orchestrator):
        projection = MonitorProjection(pipeline.ledger)

        pipeline.execute_stage("s1_prerequisites")
        snapshot = projection.snapshot(pipeline.run_id)
        assert snapshot.completed_count == 2  # s0 + s1

    def test_chain_verified_in_snapshot(self, pipeline: Orchestrator):
        projection = MonitorProjection(pipeline.ledger)
        snapshot = projection.snapshot(pipeline.run_id)
        assert snapshot.chain_valid is True


class TestWaiverIntegration:
    """Test waiver flow with the pipeline."""

    @pytest.fixture
    def waiver_manager(self, tmp_path: Path) -> WaiverManager:
        store = ContentAddressedStore(tmp_path / "artifacts")
        return WaiverManager(store)

    def test_waiver_registered_as_artifact(self, waiver_manager: WaiverManager):
        waiver = WaiverArtifact(
            scope="s55_accessibility",
            justification="Tested manually, meets WCAG 2.1 AA",
            expiration=datetime.now(timezone.utc) + timedelta(hours=24),
            approving_identity="lead-reviewer",
            risk_classification=RiskClassification.LOW,
        )
        addr = waiver_manager.register_waiver(waiver)
        assert addr.startswith("sha256:")
        assert waiver_manager.has_valid_waiver("s55_accessibility") is True

    def test_expired_waiver_not_valid(self, waiver_manager: WaiverManager):
        waiver = WaiverArtifact(
            scope="s55_accessibility",
            justification="Old waiver",
            expiration=datetime.now(timezone.utc) - timedelta(hours=1),
            approving_identity="reviewer",
            risk_classification=RiskClassification.HIGH,
        )
        with pytest.raises(WaiverExpiredError):
            waiver_manager.register_waiver(waiver)


class TestArtifactStoreIntegration:
    """Test content-addressed artifact storage."""

    def test_store_and_verify_round_trip(self, tmp_path: Path):
        store = ContentAddressedStore(tmp_path / "artifacts")
        data = b'{"test": "artifact", "version": "0.3.0"}'
        artifact = store.store(data)
        addr = artifact.content_address

        assert addr.startswith("sha256:")
        assert store.exists(addr)
        assert store.verify(addr) is True
        assert store.retrieve(addr) == data

    def test_content_addressing_deterministic(self, tmp_path: Path):
        store = ContentAddressedStore(tmp_path / "artifacts")
        data = b"deterministic content"
        a1 = store.store(data)
        a2 = store.store(data)
        # Idempotent — same content, same content address
        assert a1.content_address == a2.content_address
