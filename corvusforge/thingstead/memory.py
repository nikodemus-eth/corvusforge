"""Fleet memory — persistent, content-addressed storage in .openclaw-data/.

Implements Invariant 12: Persistent memory in .openclaw-data.

Every fleet execution produces MemoryShards — immutable, content-addressed
records stored as individual JSON files under ``.openclaw-data/shards/``.
An in-memory index (persisted to ``index.json``) allows efficient lookup
by fleet_id, stage_id, agent_id, or tags.

Data directory layout::

    .openclaw-data/
        index.json
        shards/
            {shard_id}.json
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from corvusforge.core.hasher import canonical_json_bytes, sha256_hex

logger = logging.getLogger(__name__)


class MemoryShard(BaseModel):
    """Immutable, content-addressed record of fleet execution data.

    Each shard represents a unit of persistent memory produced by a
    fleet agent during stage execution.  The ``content_hash`` is the
    SHA-256 hex digest of the canonical JSON serialization of ``content``,
    providing tamper-evident integrity.

    Parameters
    ----------
    shard_id:
        Unique identifier for this shard (UUID hex).
    fleet_id:
        The fleet that produced this shard.
    agent_id:
        The agent within the fleet that wrote this shard.
    stage_id:
        The pipeline stage during which this shard was created.
    content:
        Arbitrary JSON-serializable data captured during execution.
    content_hash:
        SHA-256 hex digest of the canonical JSON bytes of ``content``.
    created_at:
        UTC timestamp when the shard was created.
    tags:
        Optional labels for filtering and categorization.
    """

    model_config = ConfigDict(frozen=True)

    shard_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    fleet_id: str
    agent_id: str
    stage_id: str
    content: dict[str, Any]
    content_hash: str = ""
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    tags: list[str] = Field(default_factory=list)


class FleetMemory:
    """Persistent, content-addressed memory store for Thingstead fleets.

    Manages the ``.openclaw-data/`` directory structure, writes shards as
    individual JSON files, maintains an in-memory index, and supports
    querying by fleet, agent, stage, or tags.

    Parameters
    ----------
    data_dir:
        Path to the ``.openclaw-data/`` directory.  Created automatically
        (with parents) if it does not exist.
    """

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = Path(data_dir)
        self._shards_dir = self._data_dir / "shards"
        self._index_path = self._data_dir / "index.json"

        # Ensure directory structure exists
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._shards_dir.mkdir(parents=True, exist_ok=True)

        # In-memory shard index: shard_id -> MemoryShard
        self._shards: dict[str, MemoryShard] = {}

        # Load existing index from disk if available
        self.load_index()

        logger.debug(
            "FleetMemory initialized at %s with %d existing shards",
            self._data_dir,
            len(self._shards),
        )

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def write_shard(
        self,
        fleet_id: str,
        agent_id: str,
        stage_id: str,
        content: dict[str, Any],
        tags: list[str] | None = None,
    ) -> MemoryShard:
        """Create and persist a new memory shard.

        Serializes the shard content to a JSON file under
        ``data_dir/shards/{shard_id}.json`` and updates the in-memory index.

        Parameters
        ----------
        fleet_id:
            Fleet that produced this shard.
        agent_id:
            Agent within the fleet that wrote this shard.
        stage_id:
            Pipeline stage during which this shard was created.
        content:
            Arbitrary JSON-serializable data to persist.
        tags:
            Optional list of string labels for categorization.

        Returns
        -------
        MemoryShard
            The newly created shard, including its computed ``content_hash``.
        """
        content_hash = self._compute_hash(content)
        shard = MemoryShard(
            fleet_id=fleet_id,
            agent_id=agent_id,
            stage_id=stage_id,
            content=content,
            content_hash=content_hash,
            tags=tags or [],
        )

        # Write shard to disk
        shard_path = self._shards_dir / f"{shard.shard_id}.json"
        shard_path.write_text(
            shard.model_dump_json(indent=2),
            encoding="utf-8",
        )

        # Update in-memory index
        self._shards[shard.shard_id] = shard

        logger.debug(
            "Wrote shard %s for fleet=%s agent=%s stage=%s (hash=%s)",
            shard.shard_id,
            fleet_id,
            agent_id,
            stage_id,
            content_hash[:12],
        )
        return shard

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def read_shard(self, shard_id: str) -> MemoryShard | None:
        """Read a shard by its ID.

        Checks the in-memory index first, then falls back to reading
        from disk.  Returns ``None`` if the shard does not exist.

        Parameters
        ----------
        shard_id:
            The unique shard identifier.

        Returns
        -------
        MemoryShard | None
            The shard if found, otherwise ``None``.
        """
        # Check in-memory index first
        if shard_id in self._shards:
            return self._shards[shard_id]

        # Fall back to disk
        shard_path = self._shards_dir / f"{shard_id}.json"
        if not shard_path.exists():
            return None

        try:
            raw = json.loads(shard_path.read_text(encoding="utf-8"))
            shard = MemoryShard.model_validate(raw)
            # Cache in-memory
            self._shards[shard_id] = shard
            return shard
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning(
                "Failed to read shard %s from disk: %s", shard_id, exc
            )
            return None

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query_shards(
        self,
        fleet_id: str | None = None,
        stage_id: str | None = None,
        agent_id: str | None = None,
        tags: list[str] | None = None,
    ) -> list[MemoryShard]:
        """Filter shards by one or more criteria.

        All provided criteria are AND-combined: a shard must match every
        non-None filter to be included.  Tag filtering checks that all
        requested tags are present on the shard.

        Parameters
        ----------
        fleet_id:
            Filter to shards from this fleet.
        stage_id:
            Filter to shards from this pipeline stage.
        agent_id:
            Filter to shards from this specific agent.
        tags:
            Filter to shards that contain all of these tags.

        Returns
        -------
        list[MemoryShard]
            Matching shards, ordered by creation time (oldest first).
        """
        results: list[MemoryShard] = []
        for shard in self._shards.values():
            if fleet_id is not None and shard.fleet_id != fleet_id:
                continue
            if stage_id is not None and shard.stage_id != stage_id:
                continue
            if agent_id is not None and shard.agent_id != agent_id:
                continue
            if tags is not None and not all(t in shard.tags for t in tags):
                continue
            results.append(shard)

        # Sort by creation time (oldest first)
        results.sort(key=lambda s: s.created_at)
        return results

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    def get_shard_count(self) -> int:
        """Return the total number of shards in the in-memory index."""
        return len(self._shards)

    def persist_index(self) -> None:
        """Write the in-memory shard index to ``data_dir/index.json``.

        The index stores a mapping of shard_id to shard metadata,
        enabling fast reload on subsequent initialization.
        """
        index_data = {
            shard_id: shard.model_dump(mode="json")
            for shard_id, shard in self._shards.items()
        }
        self._index_path.write_text(
            json.dumps(index_data, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        logger.debug(
            "Persisted index with %d shards to %s",
            len(index_data),
            self._index_path,
        )

    def load_index(self) -> None:
        """Load the shard index from ``data_dir/index.json`` if it exists.

        Populates the in-memory index with previously persisted shards.
        Silently skips if the index file does not exist or is malformed.
        """
        if not self._index_path.exists():
            return

        try:
            raw = json.loads(self._index_path.read_text(encoding="utf-8"))
            for shard_id, shard_data in raw.items():
                try:
                    shard = MemoryShard.model_validate(shard_data)
                    self._shards[shard_id] = shard
                except Exception as exc:
                    logger.warning(
                        "Skipping malformed shard %s in index: %s",
                        shard_id,
                        exc,
                    )
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning(
                "Failed to load index from %s: %s", self._index_path, exc
            )

    # ------------------------------------------------------------------
    # Hashing
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_hash(content: dict[str, Any]) -> str:
        """Compute the SHA-256 hex digest of canonical JSON content.

        Uses ``corvusforge.core.hasher.canonical_json_bytes`` for
        deterministic serialization and ``sha256_hex`` for hashing,
        ensuring hash compatibility across the Corvusforge ecosystem.
        """
        return sha256_hex(canonical_json_bytes(content))
