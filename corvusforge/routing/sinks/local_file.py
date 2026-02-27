"""Local file sink — writes envelopes to local JSON files.

Layout: {base_path}/{run_id}/{stage_id}/{envelope_id}.json

Each envelope is serialized to canonical JSON for reproducibility and
stored in a directory hierarchy that mirrors the pipeline structure.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from corvusforge.core.hasher import canonical_json_bytes
from corvusforge.models.envelopes import EnvelopeBase
from corvusforge.routing.sinks._formatting import extract_stage_id

logger = logging.getLogger(__name__)


class LocalFileSink:
    """Writes envelopes to local JSON files.

    Parameters
    ----------
    base_path:
        Root directory for event files.  Defaults to ``.corvusforge/events``.
    """

    def __init__(self, base_path: Path | str | None = None) -> None:
        self._base = Path(base_path) if base_path else Path(".corvusforge/events")
        self._base.mkdir(parents=True, exist_ok=True)

    @property
    def sink_name(self) -> str:
        return "local_file"

    def accept(self, envelope: EnvelopeBase) -> None:
        """Write the envelope to a JSON file.

        File layout: {base_path}/{run_id}/{stage_id}/{envelope_id}.json

        For envelopes without an explicit stage_id (e.g. ``ResponseEnvelope``),
        the file is written under a ``_general`` directory.
        """
        run_id = envelope.run_id
        stage_id = extract_stage_id(envelope, default="_general")
        envelope_id = envelope.envelope_id

        target_dir = self._base / run_id / stage_id
        target_dir.mkdir(parents=True, exist_ok=True)

        target_file = target_dir / f"{envelope_id}.json"
        data = envelope.model_dump(mode="json")
        target_file.write_bytes(canonical_json_bytes(data))

        logger.debug(
            "LocalFileSink: wrote %s to %s", envelope_id, target_file
        )

    def list_events(self, run_id: str, stage_id: str | None = None) -> list[Path]:
        """List all event files for a run, optionally filtered by stage."""
        run_dir = self._base / run_id
        if not run_dir.exists():
            return []

        if stage_id:
            stage_dir = run_dir / stage_id
            if not stage_dir.exists():
                return []
            return sorted(stage_dir.glob("*.json"))

        return sorted(run_dir.rglob("*.json"))

    def read_event(self, path: Path) -> dict:
        """Read and parse a single event file."""
        return json.loads(path.read_bytes())
