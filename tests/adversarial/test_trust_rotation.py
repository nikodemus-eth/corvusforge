"""Tests for trust root rotation visibility and forensic correctness.

These tests verify that:
1. Key fingerprints are recorded in every ledger entry.
2. A trust root rotation is visible as a fingerprint change in the ledger.
3. Old entries retain the old fingerprint (immutable, sealed by hash chain).
4. Changing trust_context after entry creation would break the hash chain.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from corvusforge.bridge.crypto_bridge import (
    compute_trust_context,
    key_fingerprint,
)
from corvusforge.config import ProdConfig
from corvusforge.core.orchestrator import Orchestrator
from corvusforge.core.run_ledger import LedgerIntegrityError, RunLedger
from corvusforge.models.config import PipelineConfig
from corvusforge.models.ledger import LedgerEntry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pipeline_config(tmp_path: Path) -> PipelineConfig:
    return PipelineConfig(
        ledger_db_path=tmp_path / "ledger.db",
        artifact_store_path=tmp_path / "artifacts",
    )


# ---------------------------------------------------------------------------
# Test: Fingerprint recording
# ---------------------------------------------------------------------------


class TestFingerprintRecording:
    """Trust context must be present in every ledger entry."""

    def test_key_fingerprint_deterministic(self):
        """Same key always produces same fingerprint."""
        fp1 = key_fingerprint("abc123publickey")
        fp2 = key_fingerprint("abc123publickey")
        assert fp1 == fp2
        assert len(fp1) == 16  # 16 hex chars

    def test_different_keys_different_fingerprints(self):
        """Different keys produce different fingerprints."""
        fp1 = key_fingerprint("key-alpha")
        fp2 = key_fingerprint("key-beta")
        assert fp1 != fp2

    def test_empty_key_empty_fingerprint(self):
        """No key configured produces empty fingerprint."""
        assert key_fingerprint("") == ""

    def test_trust_context_structure(self):
        """compute_trust_context returns all three fingerprint fields."""
        ctx = compute_trust_context(
            plugin_trust_root="pub-key-1",
            waiver_signing_key="pub-key-2",
            anchor_key="pub-key-3",
        )
        assert "plugin_trust_root_fp" in ctx
        assert "waiver_signing_key_fp" in ctx
        assert "anchor_key_fp" in ctx
        assert all(len(v) == 16 for v in ctx.values())

    def test_trust_context_empty_keys(self):
        """No keys configured produces empty fingerprints."""
        ctx = compute_trust_context()
        assert ctx == {
            "plugin_trust_root_fp": "",
            "waiver_signing_key_fp": "",
            "anchor_key_fp": "",
        }

    def test_orchestrator_records_trust_context_in_entries(
        self, pipeline_config: PipelineConfig, tmp_path: Path
    ):
        """Every ledger entry must contain the trust context."""
        prod_config = ProdConfig(
            environment="development",
            plugin_trust_root="test-plugin-key-001",
            waiver_signing_key="test-waiver-key-002",
        )
        orch = Orchestrator(
            config=pipeline_config, prod_config=prod_config
        )
        orch.start_run()

        entries = orch.get_run_entries()
        assert len(entries) >= 2  # at least RUNNING + PASSED for s0_intake

        expected_plugin_fp = key_fingerprint("test-plugin-key-001")
        expected_waiver_fp = key_fingerprint("test-waiver-key-002")

        for entry in entries:
            assert entry.trust_context.get("plugin_trust_root_fp") == expected_plugin_fp
            assert entry.trust_context.get("waiver_signing_key_fp") == expected_waiver_fp
            assert entry.trust_context.get("anchor_key_fp") == ""

    def test_trust_context_persists_through_sqlite(
        self, pipeline_config: PipelineConfig, tmp_path: Path
    ):
        """Trust context must survive write-then-read through SQLite."""
        ledger = RunLedger(pipeline_config.ledger_db_path)
        entry = LedgerEntry(
            run_id="test-run",
            stage_id="s0_intake",
            state_transition="not_started->running",
            trust_context={
                "plugin_trust_root_fp": "aabbccdd11223344",
                "waiver_signing_key_fp": "eeff00112233aabb",
                "anchor_key_fp": "",
            },
        )
        sealed = ledger.append(entry)
        retrieved = ledger.get_run_entries("test-run")

        assert len(retrieved) == 1
        assert retrieved[0].trust_context == sealed.trust_context
        assert retrieved[0].trust_context["plugin_trust_root_fp"] == "aabbccdd11223344"


# ---------------------------------------------------------------------------
# Test: Trust root rotation forensics
# ---------------------------------------------------------------------------


class TestTrustRootRotation:
    """A key rotation must be forensically visible in the ledger."""

    def test_rotation_creates_visible_fingerprint_boundary(
        self, pipeline_config: PipelineConfig, tmp_path: Path
    ):
        """Simulate a key rotation between two orchestrator sessions.
        The ledger must show the old fingerprint on old entries and the
        new fingerprint on new entries."""

        # Phase 1: Run with key-alpha
        config_alpha = ProdConfig(
            environment="development",
            plugin_trust_root="key-alpha-public",
        )
        orch_alpha = Orchestrator(
            config=pipeline_config, prod_config=config_alpha, run_id="rotation-run"
        )
        orch_alpha.start_run()

        fp_alpha = key_fingerprint("key-alpha-public")
        entries_phase1 = orch_alpha.get_run_entries()
        for e in entries_phase1:
            assert e.trust_context.get("plugin_trust_root_fp") == fp_alpha

        # Phase 2: Resume with key-beta (rotation happened)
        config_beta = ProdConfig(
            environment="development",
            plugin_trust_root="key-beta-public",
        )
        Orchestrator(
            config=pipeline_config, prod_config=config_beta, run_id="rotation-run"
        )
        # Manually append a transition with the new trust context

        ledger = RunLedger(pipeline_config.ledger_db_path)
        fp_beta = key_fingerprint("key-beta-public")

        new_entry = LedgerEntry(
            run_id="rotation-run",
            stage_id="s1_prerequisites",
            state_transition="not_started->running",
            trust_context={
                "plugin_trust_root_fp": fp_beta,
                "waiver_signing_key_fp": "",
                "anchor_key_fp": "",
            },
        )
        ledger.append(new_entry)

        # Now read all entries: the boundary should be clear
        all_entries = ledger.get_run_entries("rotation-run")
        phase1_entries = [e for e in all_entries if e.trust_context.get("plugin_trust_root_fp") == fp_alpha]
        phase2_entries = [e for e in all_entries if e.trust_context.get("plugin_trust_root_fp") == fp_beta]

        assert len(phase1_entries) >= 2  # s0 RUNNING + PASSED
        assert len(phase2_entries) >= 1  # s1 RUNNING
        assert fp_alpha != fp_beta

    def test_tampering_trust_context_breaks_chain(
        self, pipeline_config: PipelineConfig, tmp_path: Path
    ):
        """If someone edits trust_context in SQLite after the fact,
        the chain hash must break because trust_context is part of
        the sealed entry payload."""
        import json
        import sqlite3

        ledger = RunLedger(pipeline_config.ledger_db_path)

        # Write some entries with a known trust context
        for i in range(3):
            entry = LedgerEntry(
                run_id="tamper-run",
                stage_id=f"s{i}",
                state_transition="not_started->running",
                trust_context={
                    "plugin_trust_root_fp": "original_fp_value",
                    "waiver_signing_key_fp": "",
                    "anchor_key_fp": "",
                },
            )
            ledger.append(entry)

        # Verify chain is valid before tampering
        assert ledger.verify_chain("tamper-run") is True

        # Tamper: change trust_context of the 2nd entry directly in SQLite
        db_path = ledger._db_path
        conn = sqlite3.connect(str(db_path))
        tampered_ctx = json.dumps({
            "plugin_trust_root_fp": "FORGED_fingerprint",
            "waiver_signing_key_fp": "",
            "anchor_key_fp": "",
        })
        conn.execute(
            "UPDATE run_ledger SET trust_context_json = ? "
            "WHERE id = (SELECT id FROM run_ledger WHERE run_id = ? ORDER BY id ASC LIMIT 1 OFFSET 1)",
            (tampered_ctx, "tamper-run"),
        )
        conn.commit()
        conn.close()

        # Chain must now be broken
        with pytest.raises(LedgerIntegrityError, match="Tampered"):
            ledger.verify_chain("tamper-run")

    def test_no_keys_configured_still_records_empty_context(
        self, pipeline_config: PipelineConfig, tmp_path: Path
    ):
        """Even with no keys configured, trust_context must be present
        and non-None in every entry."""
        orch = Orchestrator(config=pipeline_config)
        orch.start_run()

        for entry in orch.get_run_entries():
            assert isinstance(entry.trust_context, dict)
            assert "plugin_trust_root_fp" in entry.trust_context
            # Empty is fine — but the field must exist
            assert entry.trust_context["plugin_trust_root_fp"] == ""


# ---------------------------------------------------------------------------
# Test: Trust context schema version
# ---------------------------------------------------------------------------


class TestTrustContextVersion:
    """trust_context_version must be recorded and survive round-trip."""

    def test_default_version_is_one(self):
        """New LedgerEntry defaults to trust_context_version='1'."""
        entry = LedgerEntry(
            run_id="version-test",
            stage_id="s0_intake",
            state_transition="not_started->running",
        )
        assert entry.trust_context_version == "1"

    def test_version_survives_sqlite_round_trip(
        self, pipeline_config: PipelineConfig, tmp_path: Path
    ):
        """trust_context_version must persist through write-then-read."""
        ledger = RunLedger(pipeline_config.ledger_db_path)
        entry = LedgerEntry(
            run_id="version-rt",
            stage_id="s0_intake",
            state_transition="not_started->running",
            trust_context_version="1",
        )
        sealed = ledger.append(entry)
        retrieved = ledger.get_run_entries("version-rt")

        assert len(retrieved) == 1
        assert retrieved[0].trust_context_version == "1"
        assert retrieved[0].trust_context_version == sealed.trust_context_version

    def test_version_is_part_of_entry_hash(
        self, pipeline_config: PipelineConfig, tmp_path: Path
    ):
        """Changing trust_context_version should produce a different entry_hash."""
        import sqlite3

        ledger = RunLedger(pipeline_config.ledger_db_path)

        entry = LedgerEntry(
            run_id="version-hash",
            stage_id="s0_intake",
            state_transition="not_started->running",
            trust_context_version="1",
        )
        ledger.append(entry)

        # Tamper: change version in SQLite
        db_path = ledger._db_path
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "UPDATE run_ledger SET trust_context_version = '99' "
            "WHERE run_id = 'version-hash'"
        )
        conn.commit()
        conn.close()

        # Chain must now be broken
        with pytest.raises(LedgerIntegrityError, match="Tampered"):
            ledger.verify_chain("version-hash")

    def test_orchestrator_entries_have_version(
        self, pipeline_config: PipelineConfig, tmp_path: Path
    ):
        """Orchestrator-generated entries must have trust_context_version."""
        orch = Orchestrator(config=pipeline_config)
        orch.start_run()

        for entry in orch.get_run_entries():
            assert entry.trust_context_version == "1"
