"""Tests for Thingstead fleet integration — fleet lifecycle, memory persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from corvusforge.thingstead.fleet import ThingsteadFleet, FleetConfig
from corvusforge.thingstead.memory import FleetMemory, MemoryShard
from corvusforge.thingstead.models import (
    FleetSnapshot,
    AgentAssignment,
    ExecutionReceipt,
    FleetEvent,
)


class TestFleetConfig:
    def test_defaults(self):
        config = FleetConfig(fleet_name="test-fleet")
        assert config.fleet_name == "test-fleet"
        assert config.max_agents == 8
        assert config.fleet_id != ""

    def test_frozen(self):
        config = FleetConfig(fleet_name="test")
        with pytest.raises(Exception):
            config.fleet_name = "changed"


class TestFleetMemory:
    def test_write_and_read_shard(self, tmp_path: Path):
        memory = FleetMemory(tmp_path / ".openclaw-data")
        shard = memory.write_shard(
            fleet_id="fleet-1",
            agent_id="agent-1",
            stage_id="s0_intake",
            content={"key": "value"},
            tags=["test"],
        )
        assert shard.content_hash != ""
        assert shard.fleet_id == "fleet-1"

        # Read it back
        loaded = memory.read_shard(shard.shard_id)
        assert loaded is not None
        assert loaded.content_hash == shard.content_hash

    def test_query_shards_by_stage(self, tmp_path: Path):
        memory = FleetMemory(tmp_path / ".openclaw-data")
        memory.write_shard("f1", "a1", "s0", {"x": 1}, [])
        memory.write_shard("f1", "a1", "s1", {"x": 2}, [])
        memory.write_shard("f1", "a2", "s0", {"x": 3}, [])

        s0_shards = memory.query_shards(stage_id="s0")
        assert len(s0_shards) == 2

    def test_query_shards_by_tags(self, tmp_path: Path):
        memory = FleetMemory(tmp_path / ".openclaw-data")
        memory.write_shard("f1", "a1", "s0", {"x": 1}, ["important"])
        memory.write_shard("f1", "a1", "s1", {"x": 2}, ["debug"])

        important = memory.query_shards(tags=["important"])
        assert len(important) == 1

    def test_persist_and_load_index(self, tmp_path: Path):
        data_dir = tmp_path / ".openclaw-data"
        memory = FleetMemory(data_dir)
        memory.write_shard("f1", "a1", "s0", {"test": True}, [])
        memory.persist_index()

        # Reload from disk
        memory2 = FleetMemory(data_dir)
        assert memory2.get_shard_count() == 1

    def test_shard_count(self, tmp_path: Path):
        memory = FleetMemory(tmp_path / ".openclaw-data")
        assert memory.get_shard_count() == 0
        memory.write_shard("f1", "a1", "s0", {}, [])
        assert memory.get_shard_count() == 1


class TestThingsteadFleet:
    def test_spawn_agent(self, tmp_path: Path):
        config = FleetConfig(fleet_name="test", data_dir=tmp_path / ".openclaw-data")
        fleet = ThingsteadFleet(config)
        agent_id = fleet.spawn_agent("worker", "s0_intake")
        assert agent_id != ""

    def test_execute_stage(self, tmp_path: Path):
        config = FleetConfig(fleet_name="test", data_dir=tmp_path / ".openclaw-data")
        fleet = ThingsteadFleet(config)
        result = fleet.execute_stage("s0_intake", {"data": "test"})
        assert "status" in result

    def test_fleet_status(self, tmp_path: Path):
        config = FleetConfig(fleet_name="test", data_dir=tmp_path / ".openclaw-data")
        fleet = ThingsteadFleet(config)
        status = fleet.get_fleet_status()
        assert "fleet_id" in status
        assert "memory_shards" in status

    def test_shutdown(self, tmp_path: Path):
        config = FleetConfig(fleet_name="test", data_dir=tmp_path / ".openclaw-data")
        fleet = ThingsteadFleet(config)
        fleet.spawn_agent("worker", "s0")
        fleet.shutdown()
        # After shutdown, memory should be persisted
        index_path = tmp_path / ".openclaw-data" / "index.json"
        assert index_path.exists()


class TestThingsteadModels:
    def test_fleet_snapshot_frozen(self):
        snap = FleetSnapshot(
            fleet_id="f1", fleet_name="test",
            agent_count=2, shard_count=5,
            active_stages=["s0", "s1"],
        )
        assert snap.agent_count == 2
        with pytest.raises(Exception):
            snap.agent_count = 99

    def test_execution_receipt(self):
        receipt = ExecutionReceipt(
            agent_id="a1", stage_id="s0", fleet_id="f1",
            input_hash="abc", output_hash="def",
            memory_shards=["shard-1"], duration_ms=150,
        )
        assert receipt.duration_ms == 150
        assert receipt.receipt_id != ""

    def test_fleet_event(self):
        event = FleetEvent(
            fleet_id="f1",
            event_type="agent_spawned",
            details={"agent_id": "a1"},
        )
        assert event.event_type == "agent_spawned"
