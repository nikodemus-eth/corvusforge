"""Append-only, hash-chained Run Ledger backed by SQLite (Invariant 7).

The Run Ledger is the source of truth. The Build Monitor is a projection
of this ledger — it does not compute truth, it displays it.

Design:
- Append-only: only `append()` method; no update, no delete.
- Hash-chained: each entry includes SHA-256 of the previous entry.
- WAL journal mode for concurrent readers.
- entry_hash UNIQUE constraint for tamper detection.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from corvusforge.core.hasher import compute_entry_hash, sha256_hex, canonical_json_bytes
from corvusforge.models.ledger import LedgerEntry


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_CREATE_LEDGER = """
CREATE TABLE IF NOT EXISTS run_ledger (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id              TEXT NOT NULL UNIQUE,
    run_id                TEXT NOT NULL,
    stage_id              TEXT NOT NULL,
    state_transition      TEXT NOT NULL,
    timestamp_utc         TEXT NOT NULL,
    input_hash            TEXT NOT NULL DEFAULT '',
    output_hash           TEXT NOT NULL DEFAULT '',
    artifact_refs_json    TEXT NOT NULL DEFAULT '[]',
    pipeline_version      TEXT NOT NULL,
    schema_version        TEXT NOT NULL,
    toolchain_version     TEXT NOT NULL,
    ruleset_versions_json TEXT NOT NULL DEFAULT '{}',
    waiver_refs_json      TEXT NOT NULL DEFAULT '[]',
    payload_hash          TEXT NOT NULL DEFAULT '',
    previous_entry_hash   TEXT NOT NULL DEFAULT '',
    entry_hash            TEXT NOT NULL UNIQUE
);
"""

_CREATE_IDX_RUN = """
CREATE INDEX IF NOT EXISTS idx_run_id ON run_ledger(run_id, id);
"""

_CREATE_IDX_RUN_STAGE = """
CREATE INDEX IF NOT EXISTS idx_run_stage ON run_ledger(run_id, stage_id, id);
"""


class LedgerIntegrityError(RuntimeError):
    """Raised when the hash chain is broken."""


class RunLedger:
    """Append-only, hash-chained Run Ledger.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file. Created if it does not exist.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(_CREATE_LEDGER)
            conn.execute(_CREATE_IDX_RUN)
            conn.execute(_CREATE_IDX_RUN_STAGE)
            conn.commit()

    # ------------------------------------------------------------------
    # Core: append-only write
    # ------------------------------------------------------------------

    def append(self, entry: LedgerEntry) -> LedgerEntry:
        """Append an entry to the ledger, computing hash chain links.

        Returns the entry with `previous_entry_hash` and `entry_hash` set.
        This is the ONLY write method. There is no update or delete.
        """
        # Get the hash of the most recent entry for this run
        previous_hash = self._get_latest_hash(entry.run_id)

        # Build the entry dict for hashing
        entry_dict = entry.model_dump(mode="json")
        entry_dict["previous_entry_hash"] = previous_hash
        entry_dict["entry_hash"] = ""  # placeholder before computing

        # Compute the entry hash (seals this entry)
        entry_hash = compute_entry_hash(entry_dict)

        # Create the final sealed entry
        sealed = entry.model_copy(
            update={
                "previous_entry_hash": previous_hash,
                "entry_hash": entry_hash,
            }
        )

        # Persist to SQLite
        self._insert(sealed)
        return sealed

    def _insert(self, entry: LedgerEntry) -> None:
        """Insert a sealed LedgerEntry into SQLite."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO run_ledger
                    (entry_id, run_id, stage_id, state_transition, timestamp_utc,
                     input_hash, output_hash, artifact_refs_json,
                     pipeline_version, schema_version, toolchain_version,
                     ruleset_versions_json, waiver_refs_json, payload_hash,
                     previous_entry_hash, entry_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.entry_id,
                    entry.run_id,
                    entry.stage_id,
                    entry.state_transition,
                    entry.timestamp_utc.isoformat()
                    if isinstance(entry.timestamp_utc, datetime)
                    else entry.timestamp_utc,
                    entry.input_hash,
                    entry.output_hash,
                    json.dumps(entry.artifact_references),
                    entry.pipeline_version,
                    entry.schema_version,
                    entry.toolchain_version,
                    json.dumps(entry.ruleset_versions),
                    json.dumps(entry.waiver_references),
                    entry.payload_hash,
                    entry.previous_entry_hash,
                    entry.entry_hash,
                ),
            )
            conn.commit()

    def _get_latest_hash(self, run_id: str) -> str:
        """Get the entry_hash of the most recent entry for a run."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT entry_hash FROM run_ledger WHERE run_id = ? ORDER BY id DESC LIMIT 1",
                (run_id,),
            ).fetchone()
        return row[0] if row else ""

    # ------------------------------------------------------------------
    # Query methods (read-only)
    # ------------------------------------------------------------------

    def get_latest(self, run_id: str) -> LedgerEntry | None:
        """Return the most recent ledger entry for a run, or None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM run_ledger WHERE run_id = ? ORDER BY id DESC LIMIT 1",
                (run_id,),
            ).fetchone()
        return self._row_to_entry(row) if row else None

    def get_stage_history(self, run_id: str, stage_id: str) -> list[LedgerEntry]:
        """Return all ledger entries for a specific stage in a run."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM run_ledger WHERE run_id = ? AND stage_id = ? ORDER BY id ASC",
                (run_id, stage_id),
            ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def get_run_entries(self, run_id: str) -> list[LedgerEntry]:
        """Return all ledger entries for a run, ordered chronologically."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM run_ledger WHERE run_id = ? ORDER BY id ASC",
                (run_id,),
            ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def get_all_run_ids(self) -> list[str]:
        """Return all distinct run_ids in the ledger."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT run_id FROM run_ledger ORDER BY id DESC"
            ).fetchall()
        return [row[0] for row in rows]

    # ------------------------------------------------------------------
    # Chain verification
    # ------------------------------------------------------------------

    def verify_chain(self, run_id: str) -> bool:
        """Verify the hash chain integrity for a run.

        Walks all entries in order, recomputes each entry_hash, and
        verifies that previous_entry_hash links match.

        Returns True if the chain is valid, raises LedgerIntegrityError otherwise.
        """
        entries = self.get_run_entries(run_id)
        if not entries:
            return True

        prev_hash = ""
        for entry in entries:
            # Verify the previous_entry_hash link
            if entry.previous_entry_hash != prev_hash:
                raise LedgerIntegrityError(
                    f"Chain broken at entry {entry.entry_id}: "
                    f"expected previous_hash={prev_hash!r}, "
                    f"got {entry.previous_entry_hash!r}"
                )

            # Recompute and verify the entry_hash
            entry_dict = entry.model_dump(mode="json")
            expected_hash = compute_entry_hash(entry_dict)
            if entry.entry_hash != expected_hash:
                raise LedgerIntegrityError(
                    f"Tampered entry {entry.entry_id}: "
                    f"expected hash={expected_hash!r}, "
                    f"got {entry.entry_hash!r}"
                )

            prev_hash = entry.entry_hash

        return True

    # ------------------------------------------------------------------
    # External anchoring
    # ------------------------------------------------------------------

    def export_anchor(self, run_id: str) -> dict[str, Any]:
        """Export a tamper-evident anchor for external witnessing.

        The anchor captures the current chain state as a signed digest
        that can be stored outside the system (file, transparency log,
        external database).  Comparing a previously-exported anchor
        against the current chain detects retroactive rewrites.

        Returns
        -------
        dict[str, Any]
            Keys: ``run_id``, ``entry_count``, ``root_hash`` (hash of the
            last entry), ``first_entry_hash``, ``timestamp_utc``,
            ``anchor_hash`` (SHA-256 of the anchor payload itself).
        """
        entries = self.get_run_entries(run_id)
        if not entries:
            return {
                "run_id": run_id,
                "entry_count": 0,
                "root_hash": "",
                "first_entry_hash": "",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "anchor_hash": "",
            }

        anchor_payload = {
            "run_id": run_id,
            "entry_count": len(entries),
            "root_hash": entries[-1].entry_hash,
            "first_entry_hash": entries[0].entry_hash,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        anchor_hash = sha256_hex(canonical_json_bytes(anchor_payload))
        anchor_payload["anchor_hash"] = anchor_hash
        return anchor_payload

    def verify_against_anchor(self, run_id: str, anchor: dict[str, Any]) -> bool:
        """Verify the current chain against a previously exported anchor.

        Returns ``True`` if the chain matches the anchor.  Raises
        ``LedgerIntegrityError`` if the chain has diverged.

        Parameters
        ----------
        run_id:
            The run to verify.
        anchor:
            A dict previously returned by ``export_anchor()``.
        """
        entries = self.get_run_entries(run_id)

        expected_count = anchor.get("entry_count", 0)
        if len(entries) < expected_count:
            raise LedgerIntegrityError(
                f"Chain for {run_id} has {len(entries)} entries but "
                f"anchor expects at least {expected_count}."
            )

        if expected_count == 0:
            return True

        # Verify the root hash at the anchor point matches
        anchor_root = anchor.get("root_hash", "")
        anchor_first = anchor.get("first_entry_hash", "")

        if entries[0].entry_hash != anchor_first:
            raise LedgerIntegrityError(
                f"First entry hash mismatch: chain has "
                f"{entries[0].entry_hash!r}, anchor has {anchor_first!r}. "
                f"Chain may have been rewritten from the beginning."
            )

        # Find the entry at the anchor position
        anchor_idx = expected_count - 1
        if entries[anchor_idx].entry_hash != anchor_root:
            raise LedgerIntegrityError(
                f"Root hash mismatch at entry {expected_count}: chain has "
                f"{entries[anchor_idx].entry_hash!r}, anchor has "
                f"{anchor_root!r}. Chain may have been retroactively modified."
            )

        # Also verify the full chain integrity up to the anchor point
        self.verify_chain(run_id)
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_entry(row: tuple) -> LedgerEntry:
        """Convert a SQLite row tuple to a LedgerEntry."""
        (
            _id,
            entry_id,
            run_id,
            stage_id,
            state_transition,
            timestamp_utc,
            input_hash,
            output_hash,
            artifact_refs_json,
            pipeline_version,
            schema_version,
            toolchain_version,
            ruleset_versions_json,
            waiver_refs_json,
            payload_hash,
            previous_entry_hash,
            entry_hash,
        ) = row
        return LedgerEntry(
            entry_id=entry_id,
            run_id=run_id,
            stage_id=stage_id,
            state_transition=state_transition,
            timestamp_utc=timestamp_utc,
            input_hash=input_hash,
            output_hash=output_hash,
            artifact_references=json.loads(artifact_refs_json),
            pipeline_version=pipeline_version,
            schema_version=schema_version,
            toolchain_version=toolchain_version,
            ruleset_versions=json.loads(ruleset_versions_json),
            waiver_references=json.loads(waiver_refs_json),
            payload_hash=payload_hash,
            previous_entry_hash=previous_entry_hash,
            entry_hash=entry_hash,
        )
