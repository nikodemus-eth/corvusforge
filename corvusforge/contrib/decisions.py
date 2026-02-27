"""Decision registry — tracks user-supplied decisions across pipeline runs.

Every decision made through a ``UserContributionHook`` is recorded here
for audit trail, replay, and learning.  The registry is append-only:
decisions are never modified or deleted after recording.

The registry can be queried by run, stage, hook name, or outcome to
understand how operator decisions influenced pipeline behavior.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict

from corvusforge.contrib.hooks import HookOutcome, HookPriority, HookRecord

logger = logging.getLogger(__name__)


class DecisionSummary(BaseModel):
    """Aggregate summary of decisions for a run or stage."""

    model_config = ConfigDict(frozen=True)

    total_decisions: int = 0
    user_decided: int = 0
    defaults_used: int = 0
    skipped: int = 0
    failed: int = 0
    critical_decisions: int = 0
    advisory_decisions: int = 0


class DecisionRegistry:
    """Append-only registry of user decisions from contribution hooks.

    The registry tracks every ``HookRecord`` produced during pipeline
    execution.  It supports queries by run_id, stage_id, hook_name,
    and outcome for auditing and replay.

    Usage
    -----
    >>> registry = DecisionRegistry()
    >>> registry.record(hook_record)
    >>> decisions = registry.get_by_run("cf-20260226-123456-abc")
    """

    def __init__(self) -> None:
        self._records: list[HookRecord] = []

    # ------------------------------------------------------------------
    # Record
    # ------------------------------------------------------------------

    def record(self, hook_record: HookRecord) -> None:
        """Record a decision from a contribution hook.

        This is append-only — there is no update or delete.
        """
        self._records.append(hook_record)
        logger.info(
            "Decision recorded: hook=%s, run=%s, stage=%s, outcome=%s",
            hook_record.hook_name,
            hook_record.run_id,
            hook_record.stage_id,
            hook_record.outcome.value,
        )

    def record_batch(self, records: list[HookRecord]) -> None:
        """Record multiple decisions at once."""
        for record in records:
            self.record(record)

    # ------------------------------------------------------------------
    # Query by run
    # ------------------------------------------------------------------

    def get_by_run(self, run_id: str) -> list[HookRecord]:
        """Return all decisions for a pipeline run."""
        return [r for r in self._records if r.run_id == run_id]

    def get_by_stage(self, run_id: str, stage_id: str) -> list[HookRecord]:
        """Return all decisions for a specific stage in a run."""
        return [
            r
            for r in self._records
            if r.run_id == run_id and r.stage_id == stage_id
        ]

    def get_by_hook_name(self, hook_name: str) -> list[HookRecord]:
        """Return all decisions across all runs for a named hook."""
        return [r for r in self._records if r.hook_name == hook_name]

    def get_by_outcome(self, outcome: HookOutcome) -> list[HookRecord]:
        """Return all decisions with a specific outcome."""
        return [r for r in self._records if r.outcome == outcome]

    # ------------------------------------------------------------------
    # Summaries
    # ------------------------------------------------------------------

    def summarize_run(self, run_id: str) -> DecisionSummary:
        """Produce an aggregate summary for a run."""
        records = self.get_by_run(run_id)
        return self._summarize(records)

    def summarize_stage(self, run_id: str, stage_id: str) -> DecisionSummary:
        """Produce an aggregate summary for a stage."""
        records = self.get_by_stage(run_id, stage_id)
        return self._summarize(records)

    def summarize_all(self) -> DecisionSummary:
        """Produce an aggregate summary across all recorded decisions."""
        return self._summarize(self._records)

    @staticmethod
    def _summarize(records: list[HookRecord]) -> DecisionSummary:
        """Build a DecisionSummary from a list of records."""
        return DecisionSummary(
            total_decisions=len(records),
            user_decided=sum(
                1 for r in records if r.outcome == HookOutcome.USER_DECIDED
            ),
            defaults_used=sum(
                1 for r in records if r.outcome == HookOutcome.DEFAULT_USED
            ),
            skipped=sum(
                1 for r in records if r.outcome == HookOutcome.SKIPPED
            ),
            failed=sum(
                1 for r in records if r.outcome == HookOutcome.FAILED
            ),
            critical_decisions=sum(
                1 for r in records if r.priority == HookPriority.CRITICAL
            ),
            advisory_decisions=sum(
                1 for r in records if r.priority == HookPriority.ADVISORY
            ),
        )

    # ------------------------------------------------------------------
    # Replay support
    # ------------------------------------------------------------------

    def get_replay_map(self, run_id: str) -> dict[str, str]:
        """Build a hook_name -> chosen_value map for replaying a run.

        This allows a replay to use the same decisions as the original
        run without re-prompting the operator.
        """
        replay: dict[str, str] = {}
        for record in self.get_by_run(run_id):
            if record.outcome == HookOutcome.USER_DECIDED:
                replay[record.hook_name] = record.chosen_value
        return replay

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    @property
    def total_count(self) -> int:
        """Total number of recorded decisions."""
        return len(self._records)

    @property
    def all_run_ids(self) -> list[str]:
        """Return all distinct run_ids with recorded decisions."""
        return list({r.run_id for r in self._records})

    def __repr__(self) -> str:
        return f"DecisionRegistry(decisions={len(self._records)})"
