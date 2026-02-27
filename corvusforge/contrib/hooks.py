"""UserContributionHook — marks decision points in the pipeline.

Hooks are placed at stages where user input can shape the pipeline's
behavior.  In learning mode, hooks pause execution and present the
decision point to the operator.  In non-interactive mode, hooks
use default values or fail fast.

Each hook records its invocation and the decision outcome in the
decision registry for audit trail and future replay.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class HookPriority(str, Enum):
    """Priority level determining when a hook fires."""

    CRITICAL = "critical"  # Must be answered — blocks pipeline
    ADVISORY = "advisory"  # Should be answered — uses default if skipped
    INFORMATIONAL = "informational"  # FYI — never blocks


class HookOutcome(str, Enum):
    """The result of a hook invocation."""

    USER_DECIDED = "user_decided"  # User provided explicit input
    DEFAULT_USED = "default_used"  # Timeout or non-interactive, used default
    SKIPPED = "skipped"  # Hook was skipped (informational)
    FAILED = "failed"  # Hook failed to resolve


class HookRecord(BaseModel):
    """Immutable record of a hook invocation and its outcome."""

    model_config = ConfigDict(frozen=True)

    hook_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    hook_name: str
    stage_id: str
    run_id: str
    priority: HookPriority
    question: str
    options: list[str] = []
    default_value: str = ""
    outcome: HookOutcome = HookOutcome.DEFAULT_USED
    chosen_value: str = ""
    rationale: str = ""
    timestamp_utc: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class UserContributionHook:
    """Marks a decision point in the pipeline where user input is welcome.

    Hooks are registered on stages and fired when the stage reaches a
    point that benefits from human judgment.  The hook presents the
    decision to the operator (via a callback) and records the outcome.

    Parameters
    ----------
    name:
        A unique identifier for this hook (e.g. ``"test_scope_selection"``).
    stage_id:
        The pipeline stage this hook belongs to.
    question:
        The question presented to the operator.
    options:
        Optional list of predefined choices.
    default_value:
        The value used if the operator does not respond.
    priority:
        How critical this decision is to the pipeline.
    """

    def __init__(
        self,
        name: str,
        stage_id: str,
        question: str,
        *,
        options: list[str] | None = None,
        default_value: str = "",
        priority: HookPriority = HookPriority.ADVISORY,
    ) -> None:
        self.name = name
        self.stage_id = stage_id
        self.question = question
        self.options = options or []
        self.default_value = default_value
        self.priority = priority
        self._callback: Callable[[UserContributionHook], str] | None = None
        self._records: list[HookRecord] = []

    def set_callback(
        self, callback: Callable[[UserContributionHook], str]
    ) -> None:
        """Register the callback invoked when the hook fires.

        The callback receives this hook instance and should return
        the user's chosen value (or empty string for default).
        """
        self._callback = callback

    def fire(self, run_id: str) -> HookRecord:
        """Fire the hook, invoking the callback or using the default.

        Parameters
        ----------
        run_id:
            The current pipeline run ID.

        Returns
        -------
        HookRecord
            An immutable record of the decision.
        """
        outcome = HookOutcome.DEFAULT_USED
        chosen_value = self.default_value
        rationale = ""

        if self._callback is not None:
            try:
                user_input = self._callback(self)
                if user_input:
                    chosen_value = user_input
                    outcome = HookOutcome.USER_DECIDED
                    rationale = "User provided explicit input"
                else:
                    rationale = "User accepted default"
            except Exception as exc:
                logger.warning(
                    "Hook %s callback failed: %s — using default", self.name, exc
                )
                outcome = HookOutcome.FAILED
                rationale = f"Callback error: {exc}"
        else:
            if self.priority == HookPriority.INFORMATIONAL:
                outcome = HookOutcome.SKIPPED
                rationale = "Informational hook — no callback registered"
            else:
                rationale = "No callback registered — using default"

        record = HookRecord(
            hook_name=self.name,
            stage_id=self.stage_id,
            run_id=run_id,
            priority=self.priority,
            question=self.question,
            options=self.options,
            default_value=self.default_value,
            outcome=outcome,
            chosen_value=chosen_value,
            rationale=rationale,
        )

        self._records.append(record)
        logger.info(
            "Hook %s fired: outcome=%s, chosen=%s",
            self.name,
            outcome.value,
            chosen_value,
        )
        return record

    @property
    def history(self) -> list[HookRecord]:
        """Return all invocation records for this hook."""
        return list(self._records)

    def __repr__(self) -> str:
        return (
            f"UserContributionHook(name={self.name!r}, stage={self.stage_id!r}, "
            f"priority={self.priority.value!r})"
        )
