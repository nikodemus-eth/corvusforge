"""Shared test fixtures for Corvusforge."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from corvusforge.core.artifact_store import ContentAddressedStore
from corvusforge.core.prerequisite_graph import PrerequisiteGraph
from corvusforge.core.run_ledger import RunLedger
from corvusforge.core.stage_machine import StageMachine
from corvusforge.core.waiver_manager import WaiverManager
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
