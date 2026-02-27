"""Abstract base stage with enforced lifecycle (Invariants 4, 5, 7).

Every concrete stage inherits from BaseStage and implements only ``execute()``.
The ``run_stage()`` wrapper is **not overridable** — it enforces the canonical
lifecycle ordering:

    validate_prerequisites -> compute_input_hash -> execute
        -> compute_output_hash -> record

This guarantees that every stage run is hash-chained, idempotency-checked,
and ledger-recorded regardless of subclass behaviour.
"""

from __future__ import annotations

import abc
import logging
from datetime import datetime, timezone
from typing import Any, ClassVar, final

from corvusforge.core.hasher import (
    compute_input_hash,
    compute_output_hash,
)
from corvusforge.models.stages import StageState

logger = logging.getLogger(__name__)


class StagePrerequisiteError(RuntimeError):
    """Raised when a stage's prerequisites are not satisfied."""


class StageExecutionError(RuntimeError):
    """Raised when a stage's execute() method fails."""


class BaseStage(abc.ABC):
    """Abstract base for all Corvusforge pipeline stages.

    Subclasses **must** implement:
        * ``stage_id``   — unique identifier (e.g. ``"s0_intake"``).
        * ``display_name`` — human-readable name shown in the Build Monitor.
        * ``execute(run_context)`` — the stage's core logic.

    Subclasses **may** override:
        * ``is_gate`` — set to ``True`` for mandatory gate stages.
        * ``prerequisites`` — list of ``stage_id`` strings that must be
          PASSED or WAIVED before this stage can run.

    Subclasses **must not** override ``run_stage()``.
    """

    # Subclass may set True for mandatory gates (s55, s575).
    is_gate: ClassVar[bool] = False

    # ------------------------------------------------------------------
    # Abstract interface — subclasses implement these
    # ------------------------------------------------------------------

    @property
    @abc.abstractmethod
    def stage_id(self) -> str:
        """Unique stage identifier (e.g. ``'s0_intake'``)."""
        ...

    @property
    @abc.abstractmethod
    def display_name(self) -> str:
        """Human-readable display name for the Build Monitor."""
        ...

    @abc.abstractmethod
    def execute(self, run_context: dict[str, Any]) -> dict[str, Any]:
        """Execute the stage's core logic.

        Parameters
        ----------
        run_context:
            Mutable dict carrying run-wide state: ``run_id``, prior stage
            outputs, configuration, artifact references, etc.

        Returns
        -------
        dict:
            Structured result dict appropriate to the stage's purpose.
        """
        ...

    # ------------------------------------------------------------------
    # Lifecycle — NOT overridable
    # ------------------------------------------------------------------

    @final
    def run_stage(self, run_context: dict[str, Any]) -> dict[str, Any]:
        """Execute the full stage lifecycle.  **Do not override.**

        Ordering:
            1. ``validate_prerequisites(run_context)``
            2. ``compute_input_hash(run_context)``
            3. ``execute(run_context)``
            4. ``compute_output_hash(result)``
            5. ``record(run_context, result, input_hash, output_hash)``

        Returns the structured result dict produced by ``execute()``,
        augmented with ``_input_hash`` and ``_output_hash`` keys.
        """
        # 1. Validate prerequisites
        self.validate_prerequisites(run_context)

        # 2. Compute input hash for replay / idempotency detection
        input_hash = self._compute_input_hash(run_context)
        logger.info(
            "%s [%s] input_hash=%s",
            self.display_name,
            self.stage_id,
            input_hash,
        )

        # 3. Execute the stage's core logic
        try:
            result = self.execute(run_context)
        except Exception as exc:
            logger.error(
                "%s [%s] execution failed: %s",
                self.display_name,
                self.stage_id,
                exc,
            )
            raise StageExecutionError(
                f"Stage {self.stage_id} failed: {exc}"
            ) from exc

        # 4. Compute output hash for idempotency verification
        output_hash = self._compute_output_hash(result)
        logger.info(
            "%s [%s] output_hash=%s",
            self.display_name,
            self.stage_id,
            output_hash,
        )

        # 5. Record in run_context for downstream stages and the ledger
        self._record(run_context, result, input_hash, output_hash)

        # Augment result with hashes for callers that need them
        result["_input_hash"] = input_hash
        result["_output_hash"] = output_hash
        return result

    # ------------------------------------------------------------------
    # Lifecycle helpers (not overridable)
    # ------------------------------------------------------------------

    @final
    def validate_prerequisites(self, run_context: dict[str, Any]) -> None:
        """Ensure all prerequisite stages are PASSED or WAIVED.

        Reads ``stage_states`` from *run_context* (a mapping of
        ``stage_id -> StageState``).  Raises ``StagePrerequisiteError``
        if any prerequisite is not met.
        """
        stage_states: dict[str, StageState] = run_context.get(
            "stage_states", {}
        )
        prerequisites: list[str] = run_context.get(
            "stage_definitions", {}
        ).get(self.stage_id, {}).get("prerequisites", [])

        blocking: list[str] = []
        for prereq_id in prerequisites:
            state = stage_states.get(prereq_id, StageState.NOT_STARTED)
            if state not in (StageState.PASSED, StageState.WAIVED):
                blocking.append(f"{prereq_id} is {state.value}")

        if blocking:
            raise StagePrerequisiteError(
                f"Cannot run {self.stage_id}: prerequisites not met — "
                + "; ".join(blocking)
            )

    @final
    def _compute_input_hash(self, run_context: dict[str, Any]) -> str:
        """SHA-256 of canonical(stage_id + relevant inputs)."""
        # Collect deterministic inputs from context
        inputs: dict[str, Any] = {
            "run_id": run_context.get("run_id", ""),
            "prior_output_hashes": {
                sid: ctx.get("_output_hash", "")
                for sid, ctx in run_context.get("stage_results", {}).items()
            },
        }
        return compute_input_hash(self.stage_id, inputs)

    @final
    def _compute_output_hash(self, result: dict[str, Any]) -> str:
        """SHA-256 of canonical(stage_id + result)."""
        # Strip internal keys before hashing
        hashable = {
            k: v for k, v in result.items() if not k.startswith("_")
        }
        return compute_output_hash(self.stage_id, hashable)

    @final
    def _record(
        self,
        run_context: dict[str, Any],
        result: dict[str, Any],
        input_hash: str,
        output_hash: str,
    ) -> None:
        """Store stage results into the run_context for downstream stages.

        Also builds a ``LedgerEntry``-compatible dict that the orchestrator
        can persist to the Run Ledger.
        """
        run_id = run_context.get("run_id", "")

        # Store result in run_context so downstream stages can access it
        run_context.setdefault("stage_results", {})[self.stage_id] = result

        # Build a ledger-ready record for the orchestrator to persist
        ledger_record = {
            "run_id": run_id,
            "stage_id": self.stage_id,
            "state_transition": f"{StageState.RUNNING.value}->{StageState.PASSED.value}",
            "input_hash": input_hash,
            "output_hash": output_hash,
            "artifact_references": result.get("_artifact_refs", []),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        run_context.setdefault("pending_ledger_entries", []).append(
            ledger_record
        )

        logger.info(
            "%s [%s] recorded — input=%s output=%s",
            self.display_name,
            self.stage_id,
            input_hash[:12],
            output_hash[:12],
        )

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        gate = " [GATE]" if self.is_gate else ""
        return f"<{type(self).__name__} stage_id={self.stage_id!r}{gate}>"
