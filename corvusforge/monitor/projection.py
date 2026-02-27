"""MonitorProjection — pure read-only view over the RunLedger.

The Build Monitor is a PROJECTION of the Run Ledger.  It does not compute
truth — it displays it.  Every call re-reads from the ledger.  The
MonitorProjection class never maintains its own state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from corvusforge.core.production_guard import validate_trust_context_completeness
from corvusforge.core.run_ledger import RunLedger
from corvusforge.models.ledger import LedgerEntry
from corvusforge.models.stages import (
    DEFAULT_STAGE_DEFINITIONS,
    StageDefinition,
    StageState,
)


class StageStatus(BaseModel):
    """Point-in-time status of a single pipeline stage.

    Derived entirely from ledger entries — never stored independently.
    """

    model_config = ConfigDict(frozen=True)

    stage_id: str
    display_name: str
    state: StageState = StageState.NOT_STARTED
    entered_at: datetime | None = None
    block_reason: str | None = None
    upstream_ref: str | None = None
    waiver_id: str | None = None
    artifact_refs: list[str] = []


class MonitorSnapshot(BaseModel):
    """A frozen, point-in-time snapshot of a pipeline run.

    Every field is derived by re-reading the ledger.  This model is
    never persisted — it is computed fresh on every ``snapshot()`` call.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    pipeline_version: str = "0.1.0"
    stages: list[StageStatus] = []
    pending_clarifications: list[str] = []
    active_waivers: list[str] = []
    artifact_count: int = 0
    chain_valid: bool = True
    trust_context_healthy: bool = True
    trust_context_warnings: list[str] = []
    trust_context_version: str = "1"
    last_updated: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def completed_count(self) -> int:
        """Number of stages in a terminal state (PASSED or WAIVED)."""
        return sum(
            1
            for s in self.stages
            if s.state in (StageState.PASSED, StageState.WAIVED)
        )

    @property
    def total_stages(self) -> int:
        """Total number of stages in the pipeline."""
        return len(self.stages)

    @property
    def failed_stages(self) -> list[StageStatus]:
        """Stages currently in FAILED state."""
        return [s for s in self.stages if s.state == StageState.FAILED]

    @property
    def blocked_stages(self) -> list[StageStatus]:
        """Stages currently in BLOCKED state."""
        return [s for s in self.stages if s.state == StageState.BLOCKED]

    @property
    def running_stages(self) -> list[StageStatus]:
        """Stages currently in RUNNING state."""
        return [s for s in self.stages if s.state == StageState.RUNNING]


class MonitorProjection:
    """Pure read-only projection over the RunLedger.

    This class NEVER stores state.  Every method re-reads the ledger
    to compute a fresh view.

    Parameters
    ----------
    ledger:
        The RunLedger to project from.
    stage_definitions:
        Pipeline stage definitions for display names and ordering.
        Defaults to ``DEFAULT_STAGE_DEFINITIONS``.
    """

    def __init__(
        self,
        ledger: RunLedger,
        stage_definitions: list[StageDefinition] | None = None,
        *,
        trust_context_required_keys: list[str] | None = None,
    ) -> None:
        self._ledger = ledger
        self._stage_defs = {
            sd.stage_id: sd
            for sd in (stage_definitions or DEFAULT_STAGE_DEFINITIONS)
        }
        # Keep ordered list for consistent snapshot ordering
        self._stage_order = [
            sd.stage_id
            for sd in sorted(
                (stage_definitions or DEFAULT_STAGE_DEFINITIONS),
                key=lambda sd: sd.ordinal,
            )
        ]
        self._trust_required_keys = trust_context_required_keys

    def snapshot(self, run_id: str) -> MonitorSnapshot:
        """Produce a point-in-time snapshot of the pipeline run.

        Re-reads the ledger completely — no cached state.

        Parameters
        ----------
        run_id:
            The pipeline run to snapshot.

        Returns
        -------
        MonitorSnapshot
            A frozen snapshot of the current run state.
        """
        entries = self._ledger.get_run_entries(run_id)

        # Build stage states from ledger entries
        stage_states = self._compute_stage_states(entries)

        # Build StageStatus list in stage order
        stages: list[StageStatus] = []
        for stage_id in self._stage_order:
            info = stage_states.get(stage_id, {})
            sd = self._stage_defs.get(stage_id)
            display_name = sd.display_name if sd else stage_id

            stages.append(
                StageStatus(
                    stage_id=stage_id,
                    display_name=display_name,
                    state=info.get("state", StageState.NOT_STARTED),
                    entered_at=info.get("entered_at"),
                    block_reason=info.get("block_reason"),
                    upstream_ref=info.get("upstream_ref"),
                    waiver_id=info.get("waiver_id"),
                    artifact_refs=info.get("artifact_refs", []),
                )
            )

        # Collect pending clarifications
        pending_clarifications = self._find_pending_clarifications(entries)

        # Collect active waivers
        active_waivers = self._find_active_waivers(entries)

        # Count artifacts
        artifact_count = self._count_artifacts(entries)

        # Determine pipeline version from entries
        pipeline_version = "0.1.0"
        if entries:
            pipeline_version = entries[-1].pipeline_version

        # Verify chain validity (lightweight — just check structure)
        chain_valid = self._check_chain_valid(run_id)

        # Trust context health — check latest entry against required keys
        trust_warnings = self._check_trust_context_health(entries)
        trust_healthy = len(trust_warnings) == 0

        # Trust context version from latest entry
        trust_ctx_version = entries[-1].trust_context_version if entries else "1"

        # Last updated timestamp
        last_updated = entries[-1].timestamp_utc if entries else datetime.now(timezone.utc)

        return MonitorSnapshot(
            run_id=run_id,
            pipeline_version=pipeline_version,
            stages=stages,
            pending_clarifications=pending_clarifications,
            active_waivers=active_waivers,
            artifact_count=artifact_count,
            chain_valid=chain_valid,
            trust_context_healthy=trust_healthy,
            trust_context_warnings=trust_warnings,
            trust_context_version=trust_ctx_version,
            last_updated=last_updated,
        )

    def _compute_stage_states(
        self, entries: list[LedgerEntry]
    ) -> dict[str, dict[str, Any]]:
        """Replay ledger entries to compute current stage states.

        Returns a dict: stage_id -> {state, entered_at, block_reason, ...}
        """
        result: dict[str, dict[str, Any]] = {}

        for entry in entries:
            stage_id = entry.stage_id
            if stage_id not in result:
                result[stage_id] = {
                    "state": StageState.NOT_STARTED,
                    "entered_at": None,
                    "block_reason": None,
                    "upstream_ref": None,
                    "waiver_id": None,
                    "artifact_refs": [],
                }

            # Parse state transition
            if "->" in entry.state_transition:
                _, to_state_str = entry.state_transition.split("->", 1)
                try:
                    to_state = StageState(to_state_str)
                    result[stage_id]["state"] = to_state
                    result[stage_id]["entered_at"] = entry.timestamp_utc
                except ValueError:
                    pass

            # Accumulate artifact references
            if entry.artifact_references:
                result[stage_id]["artifact_refs"].extend(entry.artifact_references)

            # Track waiver references
            if entry.waiver_references:
                result[stage_id]["waiver_id"] = entry.waiver_references[0]

            # Detect block reasons from transition context
            if "->" in entry.state_transition:
                _, to_str = entry.state_transition.split("->", 1)
                if to_str == StageState.BLOCKED.value:
                    # Try to determine block reason from entry context
                    result[stage_id]["block_reason"] = (
                        f"Blocked by upstream dependency"
                    )

        return result

    def _find_pending_clarifications(self, entries: list[LedgerEntry]) -> list[str]:
        """Find unresolved clarification entries."""
        # Clarifications are tracked by envelope_ids in the entry details
        # For now, detect stages in BLOCKED state that might need clarification
        clarification_stages: list[str] = []
        blocked_stages: set[str] = set()

        for entry in entries:
            if "->" in entry.state_transition:
                _, to_str = entry.state_transition.split("->", 1)
                if to_str == StageState.BLOCKED.value:
                    blocked_stages.add(entry.stage_id)
                elif entry.stage_id in blocked_stages:
                    blocked_stages.discard(entry.stage_id)

        return list(blocked_stages)

    def _find_active_waivers(self, entries: list[LedgerEntry]) -> list[str]:
        """Collect all waiver references from ledger entries."""
        waivers: list[str] = []
        for entry in entries:
            waivers.extend(entry.waiver_references)
        return list(set(waivers))

    def _count_artifacts(self, entries: list[LedgerEntry]) -> int:
        """Count unique artifact references across all entries."""
        refs: set[str] = set()
        for entry in entries:
            refs.update(entry.artifact_references)
        return len(refs)

    def _check_trust_context_health(
        self, entries: list[LedgerEntry]
    ) -> list[str]:
        """Check whether the latest entry's trust context has all required fingerprints.

        Returns warning strings — empty means healthy.
        """
        if not entries:
            return []

        latest = entries[-1]
        return validate_trust_context_completeness(
            latest.trust_context,
            required_keys=self._trust_required_keys,
        )

    def _check_chain_valid(self, run_id: str) -> bool:
        """Check hash chain integrity without raising."""
        try:
            return self._ledger.verify_chain(run_id)
        except Exception:
            return False
