"""Canonical Run Ledger entry model (Invariant 7: append-only, hash-chained).

The Run Ledger is the source of truth for the entire pipeline. It is:
- Append-only (no UPDATE, no DELETE)
- Hash-chained (each entry links to the previous via SHA-256)
- Event-driven (one entry per state transition)
- Stage-aware (entries are scoped to run_id + stage_id)
- Version-pinned (every entry records pipeline/schema/toolchain versions)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LedgerEntry(BaseModel):
    """A single entry in the append-only Run Ledger.

    The Build Monitor is a projection of these entries. It does not
    compute truth — it displays it.
    """

    model_config = ConfigDict(frozen=True)

    entry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    stage_id: str
    state_transition: str  # "from_state->to_state", e.g. "not_started->running"
    timestamp_utc: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    input_hash: str = ""  # SHA-256 of canonical stage inputs
    output_hash: str = ""  # SHA-256 of canonical stage outputs
    artifact_references: list[str] = []  # content-addressed keys
    pipeline_version: str = "0.1.0"
    schema_version: str = "2026-02"
    toolchain_version: str = "pydantic-v2.10+typer+rich+hatchling"
    ruleset_versions: dict[str, str] = {
        "accessibility": "wcag-2.1-aa",
        "security": "1.0.0",
    }
    waiver_references: list[str] = []  # waiver_ids, if any
    previous_entry_hash: str = ""  # SHA-256 of previous entry's canonical bytes
    payload_hash: str = ""  # SHA-256 of the combined entry content
    entry_hash: str = ""  # computed after construction, seals this entry


class LedgerQuery(BaseModel):
    """Parameters for querying the Run Ledger."""

    model_config = ConfigDict(frozen=True)

    run_id: str | None = None
    stage_id: str | None = None
    limit: int = 100
    offset: int = 0
