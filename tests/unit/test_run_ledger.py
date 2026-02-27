"""Tests for the RunLedger — append-only, hash-chained, tamper-evident."""

from __future__ import annotations

import pytest

from corvusforge.core.run_ledger import RunLedger, LedgerIntegrityError
from corvusforge.models.ledger import LedgerEntry


class TestRunLedger:
    def test_append_sets_entry_hash(self, ledger: RunLedger):
        entry = LedgerEntry(
            run_id="run-1", stage_id="s0_intake",
            state_transition="not_started->running",
        )
        sealed = ledger.append(entry)
        assert sealed.entry_hash != ""
        assert sealed.previous_entry_hash == ""  # first entry

    def test_hash_chain_links(self, ledger: RunLedger):
        e1 = ledger.append(LedgerEntry(
            run_id="run-1", stage_id="s0_intake",
            state_transition="not_started->running",
        ))
        e2 = ledger.append(LedgerEntry(
            run_id="run-1", stage_id="s0_intake",
            state_transition="running->passed",
        ))
        assert e2.previous_entry_hash == e1.entry_hash

    def test_verify_chain_valid(self, ledger: RunLedger):
        ledger.append(LedgerEntry(
            run_id="run-1", stage_id="s0", state_transition="a->b",
        ))
        ledger.append(LedgerEntry(
            run_id="run-1", stage_id="s1", state_transition="a->b",
        ))
        assert ledger.verify_chain("run-1") is True

    def test_verify_chain_empty(self, ledger: RunLedger):
        assert ledger.verify_chain("nonexistent") is True

    def test_get_latest(self, ledger: RunLedger):
        ledger.append(LedgerEntry(
            run_id="run-1", stage_id="s0", state_transition="a->b",
        ))
        e2 = ledger.append(LedgerEntry(
            run_id="run-1", stage_id="s1", state_transition="c->d",
        ))
        latest = ledger.get_latest("run-1")
        assert latest is not None
        assert latest.entry_id == e2.entry_id

    def test_get_stage_history(self, ledger: RunLedger):
        ledger.append(LedgerEntry(
            run_id="run-1", stage_id="s0", state_transition="a->b",
        ))
        ledger.append(LedgerEntry(
            run_id="run-1", stage_id="s1", state_transition="a->b",
        ))
        ledger.append(LedgerEntry(
            run_id="run-1", stage_id="s0", state_transition="b->c",
        ))
        history = ledger.get_stage_history("run-1", "s0")
        assert len(history) == 2

    def test_get_run_entries(self, ledger: RunLedger):
        ledger.append(LedgerEntry(
            run_id="run-1", stage_id="s0", state_transition="a->b",
        ))
        ledger.append(LedgerEntry(
            run_id="run-2", stage_id="s0", state_transition="a->b",
        ))
        entries = ledger.get_run_entries("run-1")
        assert len(entries) == 1

    def test_get_all_run_ids(self, ledger: RunLedger):
        ledger.append(LedgerEntry(
            run_id="run-1", stage_id="s0", state_transition="a->b",
        ))
        ledger.append(LedgerEntry(
            run_id="run-2", stage_id="s0", state_transition="a->b",
        ))
        ids = ledger.get_all_run_ids()
        assert set(ids) == {"run-1", "run-2"}

    def test_entry_id_unique(self, ledger: RunLedger):
        """Each entry gets a unique UUID."""
        e1 = ledger.append(LedgerEntry(
            run_id="run-1", stage_id="s0", state_transition="a->b",
        ))
        e2 = ledger.append(LedgerEntry(
            run_id="run-1", stage_id="s0", state_transition="b->c",
        ))
        assert e1.entry_id != e2.entry_id
