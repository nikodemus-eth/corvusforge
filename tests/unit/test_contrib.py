"""Unit tests for UserContributionHook and DecisionRegistry.

Phase 6E of v0.4.0: Tests hook fire/callback/history and
decision registry record/query/replay/summary.
"""

from __future__ import annotations

from corvusforge.contrib.decisions import DecisionRegistry
from corvusforge.contrib.hooks import (
    HookOutcome,
    HookPriority,
    HookRecord,
    UserContributionHook,
)

# ---------------------------------------------------------------------------
# Test: UserContributionHook
# ---------------------------------------------------------------------------


class TestUserContributionHook:
    """Hooks must fire correctly with and without callbacks."""

    def test_fire_uses_default_without_callback(self):
        """No callback registered → default value used."""
        hook = UserContributionHook(
            name="test-hook",
            stage_id="s0_intake",
            question="Choose wisely?",
            default_value="safe-choice",
        )
        record = hook.fire(run_id="run-001")

        assert record.outcome == HookOutcome.DEFAULT_USED
        assert record.chosen_value == "safe-choice"
        assert record.hook_name == "test-hook"
        assert record.run_id == "run-001"

    def test_fire_with_callback_user_decided(self):
        """Callback that returns a value → USER_DECIDED outcome."""
        hook = UserContributionHook(
            name="interactive-hook",
            stage_id="s1_prerequisites",
            question="Pick a strategy?",
            options=["option-a", "option-b"],
        )
        hook.set_callback(lambda h: "option-b")

        record = hook.fire(run_id="run-002")

        assert record.outcome == HookOutcome.USER_DECIDED
        assert record.chosen_value == "option-b"

    def test_fire_with_callback_returns_empty(self):
        """Callback that returns empty string → DEFAULT_USED."""
        hook = UserContributionHook(
            name="empty-hook",
            stage_id="s2_environment",
            question="Accept default?",
            default_value="default-val",
        )
        hook.set_callback(lambda h: "")

        record = hook.fire(run_id="run-003")

        assert record.outcome == HookOutcome.DEFAULT_USED
        assert record.chosen_value == "default-val"

    def test_fire_with_failing_callback(self):
        """Callback that raises → FAILED outcome, default value used."""
        hook = UserContributionHook(
            name="broken-hook",
            stage_id="s3_test_contract",
            question="Will fail?",
            default_value="fallback",
        )
        hook.set_callback(lambda h: (_ for _ in ()).throw(RuntimeError("boom")))

        record = hook.fire(run_id="run-004")

        assert record.outcome == HookOutcome.FAILED
        assert record.chosen_value == "fallback"

    def test_informational_hook_skipped_without_callback(self):
        """INFORMATIONAL priority + no callback → SKIPPED."""
        hook = UserContributionHook(
            name="info-hook",
            stage_id="s0_intake",
            question="FYI:",
            priority=HookPriority.INFORMATIONAL,
        )
        record = hook.fire(run_id="run-005")

        assert record.outcome == HookOutcome.SKIPPED

    def test_hook_history_accumulates(self):
        """Multiple fire() calls should accumulate in history."""
        hook = UserContributionHook(
            name="multi-hook",
            stage_id="s0_intake",
            question="Again?",
        )
        hook.fire(run_id="run-a")
        hook.fire(run_id="run-b")
        hook.fire(run_id="run-c")

        assert len(hook.history) == 3
        assert hook.history[0].run_id == "run-a"
        assert hook.history[2].run_id == "run-c"

    def test_hook_repr(self):
        """repr should include name, stage, and priority."""
        hook = UserContributionHook(
            name="repr-hook",
            stage_id="s0_intake",
            question="?",
            priority=HookPriority.CRITICAL,
        )
        r = repr(hook)
        assert "repr-hook" in r
        assert "critical" in r


# ---------------------------------------------------------------------------
# Test: DecisionRegistry
# ---------------------------------------------------------------------------


class TestDecisionRegistry:
    """DecisionRegistry must support append-only recording and query."""

    def _make_record(
        self,
        hook_name: str = "test-hook",
        run_id: str = "run-001",
        stage_id: str = "s0_intake",
        outcome: HookOutcome = HookOutcome.USER_DECIDED,
        priority: HookPriority = HookPriority.ADVISORY,
        chosen_value: str = "choice",
    ) -> HookRecord:
        return HookRecord(
            hook_name=hook_name,
            run_id=run_id,
            stage_id=stage_id,
            priority=priority,
            question="Test question?",
            outcome=outcome,
            chosen_value=chosen_value,
        )

    def test_record_and_count(self):
        """record() should increment total_count."""
        reg = DecisionRegistry()
        assert reg.total_count == 0

        reg.record(self._make_record())
        assert reg.total_count == 1

    def test_record_batch(self):
        """record_batch should add multiple records."""
        reg = DecisionRegistry()
        records = [self._make_record(run_id=f"run-{i}") for i in range(5)]
        reg.record_batch(records)
        assert reg.total_count == 5

    def test_get_by_run(self):
        """get_by_run should filter by run_id."""
        reg = DecisionRegistry()
        reg.record(self._make_record(run_id="run-a"))
        reg.record(self._make_record(run_id="run-b"))
        reg.record(self._make_record(run_id="run-a"))

        results = reg.get_by_run("run-a")
        assert len(results) == 2

    def test_get_by_stage(self):
        """get_by_stage should filter by run_id AND stage_id."""
        reg = DecisionRegistry()
        reg.record(self._make_record(run_id="run-x", stage_id="s0_intake"))
        reg.record(self._make_record(run_id="run-x", stage_id="s1_prerequisites"))
        reg.record(self._make_record(run_id="run-y", stage_id="s0_intake"))

        results = reg.get_by_stage("run-x", "s0_intake")
        assert len(results) == 1

    def test_get_by_hook_name(self):
        """get_by_hook_name should filter across all runs."""
        reg = DecisionRegistry()
        reg.record(self._make_record(hook_name="scope"))
        reg.record(self._make_record(hook_name="scope"))
        reg.record(self._make_record(hook_name="strategy"))

        assert len(reg.get_by_hook_name("scope")) == 2
        assert len(reg.get_by_hook_name("strategy")) == 1

    def test_get_by_outcome(self):
        """get_by_outcome should filter by HookOutcome."""
        reg = DecisionRegistry()
        reg.record(self._make_record(outcome=HookOutcome.USER_DECIDED))
        reg.record(self._make_record(outcome=HookOutcome.DEFAULT_USED))
        reg.record(self._make_record(outcome=HookOutcome.USER_DECIDED))

        assert len(reg.get_by_outcome(HookOutcome.USER_DECIDED)) == 2
        assert len(reg.get_by_outcome(HookOutcome.DEFAULT_USED)) == 1

    def test_summarize_run(self):
        """summarize_run should produce correct aggregate counts."""
        reg = DecisionRegistry()
        reg.record(self._make_record(
            run_id="run-s", outcome=HookOutcome.USER_DECIDED,
            priority=HookPriority.CRITICAL,
        ))
        reg.record(self._make_record(
            run_id="run-s", outcome=HookOutcome.DEFAULT_USED,
            priority=HookPriority.ADVISORY,
        ))
        reg.record(self._make_record(run_id="run-s", outcome=HookOutcome.SKIPPED))
        reg.record(self._make_record(run_id="other", outcome=HookOutcome.FAILED))

        summary = reg.summarize_run("run-s")
        assert summary.total_decisions == 3
        assert summary.user_decided == 1
        assert summary.defaults_used == 1
        assert summary.skipped == 1
        assert summary.critical_decisions == 1

    def test_get_replay_map(self):
        """get_replay_map should return only USER_DECIDED hook_name->value."""
        reg = DecisionRegistry()
        reg.record(self._make_record(
            run_id="replay-run", hook_name="h1",
            outcome=HookOutcome.USER_DECIDED, chosen_value="val-1"
        ))
        reg.record(self._make_record(
            run_id="replay-run", hook_name="h2",
            outcome=HookOutcome.DEFAULT_USED, chosen_value="val-2"
        ))

        replay = reg.get_replay_map("replay-run")
        assert replay == {"h1": "val-1"}

    def test_all_run_ids(self):
        """all_run_ids should return distinct run IDs."""
        reg = DecisionRegistry()
        reg.record(self._make_record(run_id="run-1"))
        reg.record(self._make_record(run_id="run-2"))
        reg.record(self._make_record(run_id="run-1"))

        ids = sorted(reg.all_run_ids)
        assert ids == ["run-1", "run-2"]
