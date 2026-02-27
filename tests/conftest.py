"""Shared test fixtures for Corvusforge."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from corvusforge.core.artifact_store import ContentAddressedStore
from corvusforge.core.prerequisite_graph import PrerequisiteGraph
from corvusforge.core.run_ledger import RunLedger
from corvusforge.core.stage_machine import StageMachine
from corvusforge.core.waiver_manager import WaiverManager
from corvusforge.models.envelopes import (
    ArtifactEnvelope,
    EventEnvelope,
    FailureEnvelope,
    WorkOrderEnvelope,
)
from corvusforge.models.stages import DEFAULT_STAGE_DEFINITIONS


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for test artifacts."""
    return tmp_path


@pytest.fixture
def ledger(tmp_dir: Path) -> RunLedger:
    """Provide a fresh RunLedger backed by a temp SQLite database."""
    return RunLedger(tmp_dir / "test_ledger.db")


@pytest.fixture
def artifact_store(tmp_dir: Path) -> ContentAddressedStore:
    """Provide a fresh ContentAddressedStore in a temp directory."""
    return ContentAddressedStore(tmp_dir / "artifacts")


@pytest.fixture
def graph() -> PrerequisiteGraph:
    """Provide a PrerequisiteGraph with the default pipeline stages."""
    return PrerequisiteGraph(DEFAULT_STAGE_DEFINITIONS)


@pytest.fixture
def stage_machine(ledger: RunLedger, graph: PrerequisiteGraph) -> StageMachine:
    """Provide a StageMachine wired to test ledger and graph."""
    return StageMachine(ledger, graph)


@pytest.fixture
def waiver_manager(artifact_store: ContentAddressedStore) -> WaiverManager:
    """Provide a WaiverManager backed by the test artifact store."""
    return WaiverManager(artifact_store)


@pytest.fixture
def run_id() -> str:
    """Provide a deterministic test run ID."""
    return "cf-test-run-001"


# ---------------------------------------------------------------------------
# Envelope factories — shared across test modules
# ---------------------------------------------------------------------------


@pytest.fixture
def make_event_envelope() -> Callable[..., EventEnvelope]:
    """Factory fixture: build an EventEnvelope with sensible defaults."""

    def _factory(
        run_id: str = "test-run-001",
        stage_id: str = "s0_intake",
        event_type: str = "test_event",
        **overrides: Any,
    ) -> EventEnvelope:
        defaults: dict[str, Any] = {
            "run_id": run_id,
            "source_node_id": "src-node",
            "destination_node_id": "dst-node",
            "stage_id": stage_id,
            "event_type": event_type,
        }
        defaults.update(overrides)
        return EventEnvelope(**defaults)

    return _factory


@pytest.fixture
def make_work_order_envelope() -> Callable[..., WorkOrderEnvelope]:
    """Factory fixture: build a WorkOrderEnvelope with sensible defaults."""

    def _factory(
        run_id: str = "test-run-001",
        stage_id: str = "s0_intake",
        **overrides: Any,
    ) -> WorkOrderEnvelope:
        defaults: dict[str, Any] = {
            "run_id": run_id,
            "source_node_id": "src-node",
            "destination_node_id": "dst-node",
            "stage_id": stage_id,
            "work_specification": {"test": True},
        }
        defaults.update(overrides)
        return WorkOrderEnvelope(**defaults)

    return _factory


@pytest.fixture
def make_failure_envelope() -> Callable[..., FailureEnvelope]:
    """Factory fixture: build a FailureEnvelope with sensible defaults."""

    def _factory(
        run_id: str = "test-run-001",
        error_message: str = "Test error",
        **overrides: Any,
    ) -> FailureEnvelope:
        defaults: dict[str, Any] = {
            "run_id": run_id,
            "source_node_id": "src-node",
            "destination_node_id": "dst-node",
            "error_code": "TEST_ERR",
            "error_message": error_message,
            "failed_stage_id": "s0_intake",
        }
        defaults.update(overrides)
        return FailureEnvelope(**defaults)

    return _factory


@pytest.fixture
def make_artifact_envelope() -> Callable[..., ArtifactEnvelope]:
    """Factory fixture: build an ArtifactEnvelope with sensible defaults."""

    def _factory(
        run_id: str = "test-run-001",
        artifact_ref: str = "sha256:abc123",
        **overrides: Any,
    ) -> ArtifactEnvelope:
        defaults: dict[str, Any] = {
            "run_id": run_id,
            "source_node_id": "src-node",
            "destination_node_id": "dst-node",
            "artifact_ref": artifact_ref,
            "artifact_type": "test_artifact",
        }
        defaults.update(overrides)
        return ArtifactEnvelope(**defaults)

    return _factory


@pytest.fixture
def event_envelope(make_event_envelope: Callable[..., EventEnvelope]) -> EventEnvelope:
    """Convenience: a ready-made EventEnvelope with test defaults."""
    return make_event_envelope()
