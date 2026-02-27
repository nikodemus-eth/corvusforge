"""Tests for all Pydantic data models — validation, immutability, defaults."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from corvusforge.models.config import PipelineConfig, RunConfig
from corvusforge.models.envelopes import (
    ENVELOPE_TYPE_MAP,
    EnvelopeKind,
    FailureEnvelope,
    WorkOrderEnvelope,
)
from corvusforge.models.ledger import LedgerEntry
from corvusforge.models.stages import (
    DEFAULT_STAGE_DEFINITIONS,
    VALID_TRANSITIONS,
    StageDefinition,
    StageState,
)
from corvusforge.models.versioning import VersionPin
from corvusforge.models.waivers import RiskClassification, WaiverArtifact


class TestStageModels:
    def test_stage_state_values(self):
        assert StageState.NOT_STARTED == "not_started"
        assert StageState.PASSED == "passed"
        assert StageState.WAIVED == "waived"

    def test_valid_transitions_terminal_states(self):
        """PASSED and WAIVED are terminal — no outgoing transitions."""
        assert VALID_TRANSITIONS[StageState.PASSED] == set()
        assert VALID_TRANSITIONS[StageState.WAIVED] == set()

    def test_valid_transitions_not_started(self):
        allowed = VALID_TRANSITIONS[StageState.NOT_STARTED]
        assert StageState.RUNNING in allowed
        assert StageState.BLOCKED in allowed

    def test_default_stage_definitions_count(self):
        assert len(DEFAULT_STAGE_DEFINITIONS) == 10

    def test_default_stages_ordered(self):
        ordinals = [sd.ordinal for sd in DEFAULT_STAGE_DEFINITIONS]
        assert ordinals == sorted(ordinals)

    def test_accessibility_gate_is_mandatory(self):
        gate = next(sd for sd in DEFAULT_STAGE_DEFINITIONS if sd.stage_id == "s55_accessibility")
        assert gate.is_mandatory_gate is True

    def test_security_gate_is_mandatory(self):
        gate = next(sd for sd in DEFAULT_STAGE_DEFINITIONS if sd.stage_id == "s575_security")
        assert gate.is_mandatory_gate is True

    def test_verification_requires_both_gates(self):
        verif = next(sd for sd in DEFAULT_STAGE_DEFINITIONS if sd.stage_id == "s6_verification")
        assert "s55_accessibility" in verif.prerequisites
        assert "s575_security" in verif.prerequisites

    def test_stage_definition_frozen(self):
        sd = StageDefinition(stage_id="test", display_name="Test", ordinal=0.0)
        with pytest.raises(Exception):
            sd.stage_id = "changed"


class TestEnvelopeModels:
    def test_all_envelope_kinds_have_models(self):
        for kind in EnvelopeKind:
            assert kind in ENVELOPE_TYPE_MAP

    def test_work_order_envelope(self):
        env = WorkOrderEnvelope(
            run_id="test-run",
            source_node_id="node-a",
            destination_node_id="node-b",
            stage_id="s0_intake",
            work_specification={"task": "init"},
        )
        assert env.envelope_kind == EnvelopeKind.WORK_ORDER
        assert env.stage_id == "s0_intake"

    def test_failure_envelope(self):
        env = FailureEnvelope(
            run_id="test-run",
            source_node_id="node-a",
            destination_node_id="node-b",
            error_code="E001",
            error_message="Something failed",
            failed_stage_id="s5_implementation",
            recoverable=True,
        )
        assert env.recoverable is True

    def test_envelope_frozen(self):
        env = WorkOrderEnvelope(
            run_id="test", source_node_id="a", destination_node_id="b",
            stage_id="s0",
        )
        with pytest.raises(Exception):
            env.run_id = "changed"


class TestLedgerEntry:
    def test_defaults(self):
        entry = LedgerEntry(
            run_id="test-run",
            stage_id="s0_intake",
            state_transition="not_started->running",
        )
        assert entry.pipeline_version == "0.1.0"
        assert entry.schema_version == "2026-02"
        assert entry.entry_hash == ""

    def test_frozen(self):
        entry = LedgerEntry(run_id="test", stage_id="s0", state_transition="a->b")
        with pytest.raises(Exception):
            entry.run_id = "changed"


class TestWaiverModels:
    def test_waiver_not_expired(self):
        waiver = WaiverArtifact(
            scope="s55_accessibility",
            justification="Test waiver",
            expiration=datetime.now(timezone.utc) + timedelta(hours=1),
            approving_identity="test-approver",
            risk_classification=RiskClassification.LOW,
        )
        assert waiver.is_expired is False

    def test_waiver_expired(self):
        waiver = WaiverArtifact(
            scope="s55_accessibility",
            justification="Old waiver",
            expiration=datetime.now(timezone.utc) - timedelta(hours=1),
            approving_identity="test-approver",
            risk_classification=RiskClassification.HIGH,
        )
        assert waiver.is_expired is True


class TestVersionPin:
    def test_defaults(self):
        pin = VersionPin()
        assert pin.pipeline_version == "0.1.0"
        assert pin.schema_version == "2026-02"


class TestConfig:
    def test_pipeline_config_defaults(self):
        config = PipelineConfig()
        assert config.project_name == "corvusforge"

    def test_run_config_generates_id(self):
        rc = RunConfig()
        assert rc.run_id.startswith("cf-")
