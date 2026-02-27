"""Adversarial tests — memory shard integrity and run isolation.

These tests verify that:
1. Tampered shard content is detected on verification
2. Shards are properly isolated by run_id
3. Snapshot verification catches corrupted shards
4. Missing content_hash is flagged
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from corvusforge.thingstead.memory import FleetMemory, MemoryShard, ShardIntegrityError


class TestShardTamperDetection:
    """Verify that shard integrity checks catch modifications."""

    @pytest.fixture
    def memory(self, tmp_path: Path) -> FleetMemory:
        return FleetMemory(tmp_path / "openclaw-data")

    def test_valid_shard_passes_verification(self, memory):
        """A shard with correct content_hash passes verify_shard."""
        shard = memory.write_shard(
            fleet_id="fleet-1", agent_id="agent-1",
            stage_id="s1", content={"key": "value"},
            run_id="run-001",
        )
        assert memory.verify_shard(shard) is True

    def test_tampered_content_detected(self, memory):
        """Modifying shard content after creation must be detected."""
        shard = memory.write_shard(
            fleet_id="fleet-1", agent_id="agent-1",
            stage_id="s1", content={"key": "original"},
            run_id="run-001",
        )
        # Create a tampered copy (since MemoryShard is frozen,
        # we simulate what loading a corrupted file would produce)
        tampered = MemoryShard(
            shard_id=shard.shard_id,
            run_id=shard.run_id,
            fleet_id=shard.fleet_id,
            agent_id=shard.agent_id,
            stage_id=shard.stage_id,
            content={"key": "TAMPERED"},  # changed content
            content_hash=shard.content_hash,  # old hash
            created_at=shard.created_at,
            tags=shard.tags,
        )
        with pytest.raises(ShardIntegrityError, match="integrity check failed"):
            memory.verify_shard(tampered)

    def test_empty_content_hash_detected(self, memory):
        """A shard with empty content_hash fails verification."""
        shard = MemoryShard(
            fleet_id="fleet-1", agent_id="agent-1",
            stage_id="s1", content={"key": "value"},
            content_hash="",  # missing hash
            run_id="run-001",
        )
        with pytest.raises(ShardIntegrityError):
            memory.verify_shard(shard)


class TestRunIsolation:
    """Verify that shards are properly scoped to runs."""

    @pytest.fixture
    def memory(self, tmp_path: Path) -> FleetMemory:
        return FleetMemory(tmp_path / "openclaw-data")

    def test_shards_filtered_by_run_id(self, memory):
        """query_shards with run_id only returns matching shards."""
        memory.write_shard(
            fleet_id="f1", agent_id="a1", stage_id="s1",
            content={"data": "run1"}, run_id="run-001",
        )
        memory.write_shard(
            fleet_id="f1", agent_id="a1", stage_id="s1",
            content={"data": "run2"}, run_id="run-002",
        )
        memory.write_shard(
            fleet_id="f1", agent_id="a1", stage_id="s1",
            content={"data": "run1-again"}, run_id="run-001",
        )

        run1_shards = memory.query_shards(run_id="run-001")
        assert len(run1_shards) == 2
        assert all(s.run_id == "run-001" for s in run1_shards)

        run2_shards = memory.query_shards(run_id="run-002")
        assert len(run2_shards) == 1

    def test_snapshot_for_run_returns_only_that_run(self, memory):
        """snapshot_for_run must return only shards for the given run."""
        memory.write_shard(
            fleet_id="f1", agent_id="a1", stage_id="s1",
            content={"data": "A"}, run_id="run-A",
        )
        memory.write_shard(
            fleet_id="f1", agent_id="a1", stage_id="s1",
            content={"data": "B"}, run_id="run-B",
        )

        snapshot = memory.snapshot_for_run("run-A")
        assert len(snapshot) == 1
        assert snapshot[0].run_id == "run-A"

    def test_snapshot_verifies_integrity(self, memory):
        """snapshot_for_run with verify=True catches tampered shards."""
        shard = memory.write_shard(
            fleet_id="f1", agent_id="a1", stage_id="s1",
            content={"data": "original"}, run_id="run-verify",
        )

        # Tamper: overwrite the shard file on disk with wrong content
        shard_path = memory._shards_dir / f"{shard.shard_id}.json"
        raw = json.loads(shard_path.read_text())
        raw["content"]["data"] = "TAMPERED"
        shard_path.write_text(json.dumps(raw))

        # Force reload from disk by clearing in-memory cache
        tampered_shard = MemoryShard.model_validate(raw)
        memory._shards[shard.shard_id] = tampered_shard

        with pytest.raises(ShardIntegrityError):
            memory.snapshot_for_run("run-verify", verify=True)

    def test_legacy_shards_have_empty_run_id(self, memory):
        """Shards created without run_id get empty string (backward compat)."""
        shard = memory.write_shard(
            fleet_id="f1", agent_id="a1", stage_id="s1",
            content={"legacy": True},
            # no run_id parameter
        )
        assert shard.run_id == ""
