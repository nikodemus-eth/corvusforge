"""Adversarial tests — ledger tampering and chain integrity.

These tests verify that the Run Ledger detects:
1. Corrupted entry hashes (tampered content)
2. Broken chain links (reordered/deleted entries)
3. Retroactive rewrites (full chain recalculation)
4. External anchor divergence
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from corvusforge.core.run_ledger import LedgerIntegrityError, RunLedger
from corvusforge.models.ledger import LedgerEntry


class TestLedgerTamperDetection:
    """Direct SQLite manipulation to simulate an attacker with DB access."""

    @pytest.fixture
    def seeded_ledger(self, tmp_path: Path) -> tuple[RunLedger, str]:
        """Seed a ledger with 5 entries for a single run."""
        ledger = RunLedger(tmp_path / "ledger.db")
        run_id = "cf-adversarial-001"
        for i in range(5):
            ledger.append(LedgerEntry(
                run_id=run_id,
                stage_id=f"s{i}",
                state_transition="not_started->running",
            ))
        return ledger, run_id

    def test_corrupted_entry_hash_detected(self, seeded_ledger):
        """Modify an entry_hash directly in SQLite. verify_chain must catch it."""
        ledger, run_id = seeded_ledger
        # Tamper: overwrite the entry_hash of the 3rd entry
        db_path = ledger._db_path
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "UPDATE run_ledger SET entry_hash = 'TAMPERED' "
            "WHERE id = (SELECT id FROM run_ledger WHERE run_id = ? ORDER BY id ASC LIMIT 1 OFFSET 2)",
            (run_id,),
        )
        conn.commit()
        conn.close()

        with pytest.raises(LedgerIntegrityError, match="(Chain broken|Tampered)"):
            ledger.verify_chain(run_id)

    def test_corrupted_payload_detected(self, seeded_ledger):
        """Modify a state_transition field. Hash recomputation must detect it."""
        ledger, run_id = seeded_ledger
        db_path = ledger._db_path
        conn = sqlite3.connect(str(db_path))
        # Tamper the state_transition of entry 2
        conn.execute(
            "UPDATE run_ledger SET state_transition = 'injected->malicious' "
            "WHERE run_id = ? AND id = (SELECT id FROM run_ledger WHERE run_id = ? ORDER BY id ASC LIMIT 1 OFFSET 1)",
            (run_id, run_id),
        )
        conn.commit()
        conn.close()

        with pytest.raises(LedgerIntegrityError, match="Tampered"):
            ledger.verify_chain(run_id)

    def test_deleted_entry_breaks_chain(self, seeded_ledger):
        """Delete a middle entry. Chain linkage must fail."""
        ledger, run_id = seeded_ledger
        db_path = ledger._db_path
        conn = sqlite3.connect(str(db_path))
        # Delete the 2nd entry
        second_id = conn.execute(
            "SELECT id FROM run_ledger WHERE run_id = ? ORDER BY id ASC LIMIT 1 OFFSET 1",
            (run_id,),
        ).fetchone()[0]
        conn.execute("DELETE FROM run_ledger WHERE id = ?", (second_id,))
        conn.commit()
        conn.close()

        with pytest.raises(LedgerIntegrityError, match="Chain broken"):
            ledger.verify_chain(run_id)

    def test_broken_chain_link_detected(self, seeded_ledger):
        """Corrupt a previous_entry_hash link. Chain linkage must fail."""
        ledger, run_id = seeded_ledger
        db_path = ledger._db_path
        conn = sqlite3.connect(str(db_path))
        # Break the chain by corrupting the 3rd entry's previous_entry_hash
        conn.execute(
            "UPDATE run_ledger SET previous_entry_hash = 'WRONG_LINK' "
            "WHERE id = (SELECT id FROM run_ledger WHERE run_id = ? ORDER BY id ASC LIMIT 1 OFFSET 2)",
            (run_id,),
        )
        conn.commit()
        conn.close()

        with pytest.raises(LedgerIntegrityError, match="Chain broken"):
            ledger.verify_chain(run_id)


class TestExternalAnchoring:
    """Test that external anchors detect chain rewrites."""

    def test_anchor_export_round_trip(self, tmp_path: Path):
        """Export an anchor, verify it matches."""
        ledger = RunLedger(tmp_path / "ledger.db")
        run_id = "cf-anchor-001"
        for i in range(3):
            ledger.append(LedgerEntry(
                run_id=run_id, stage_id=f"s{i}",
                state_transition="not_started->running",
            ))

        anchor = ledger.export_anchor(run_id)
        assert anchor["entry_count"] == 3
        assert anchor["root_hash"] != ""
        assert anchor["anchor_hash"] != ""
        assert ledger.verify_against_anchor(run_id, anchor) is True

    def test_anchor_detects_appended_then_rewritten(self, tmp_path: Path):
        """Export anchor at entry 3, then rewrite entry 2. Must detect."""
        ledger = RunLedger(tmp_path / "ledger.db")
        run_id = "cf-anchor-002"
        for i in range(3):
            ledger.append(LedgerEntry(
                run_id=run_id, stage_id=f"s{i}",
                state_transition="not_started->running",
            ))

        anchor = ledger.export_anchor(run_id)

        # Tamper: corrupt entry 2's state_transition
        conn = sqlite3.connect(str(tmp_path / "ledger.db"))
        conn.execute(
            "UPDATE run_ledger SET state_transition = 'HACKED' "
            "WHERE run_id = ? AND id = (SELECT id FROM run_ledger WHERE run_id = ? ORDER BY id ASC LIMIT 1 OFFSET 1)",
            (run_id, run_id),
        )
        conn.commit()
        conn.close()

        with pytest.raises(LedgerIntegrityError):
            ledger.verify_against_anchor(run_id, anchor)

    def test_anchor_detects_truncated_chain(self, tmp_path: Path):
        """Export anchor at entry 5, then delete entries. Must detect."""
        ledger = RunLedger(tmp_path / "ledger.db")
        run_id = "cf-anchor-003"
        for i in range(5):
            ledger.append(LedgerEntry(
                run_id=run_id, stage_id=f"s{i}",
                state_transition="not_started->running",
            ))

        anchor = ledger.export_anchor(run_id)

        # Delete last 2 entries
        conn = sqlite3.connect(str(tmp_path / "ledger.db"))
        conn.execute(
            "DELETE FROM run_ledger WHERE run_id = ? AND id IN "
            "(SELECT id FROM run_ledger WHERE run_id = ? ORDER BY id DESC LIMIT 2)",
            (run_id, run_id),
        )
        conn.commit()
        conn.close()

        with pytest.raises(LedgerIntegrityError, match="entries but anchor expects"):
            ledger.verify_against_anchor(run_id, anchor)

    def test_empty_chain_anchor(self, tmp_path: Path):
        """Anchor on empty chain should work."""
        ledger = RunLedger(tmp_path / "ledger.db")
        anchor = ledger.export_anchor("nonexistent")
        assert anchor["entry_count"] == 0
        assert ledger.verify_against_anchor("nonexistent", anchor) is True
