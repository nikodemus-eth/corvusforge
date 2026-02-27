"""Artifact store sink — routes envelopes to the ContentAddressedStore.

Every envelope is serialized to canonical JSON and stored as a
content-addressed artifact.  This gives every event an immutable,
tamper-evident record in the artifact store alongside code artifacts.
"""

from __future__ import annotations

import logging

from corvusforge.core.artifact_store import ContentAddressedStore
from corvusforge.core.hasher import canonical_json_bytes
from corvusforge.models.envelopes import EnvelopeBase

logger = logging.getLogger(__name__)


class ArtifactStoreSink:
    """Routes envelopes to the ContentAddressedStore.

    Each envelope is stored as a content-addressed artifact with
    ``artifact_type="envelope"`` and metadata recording the run_id,
    envelope_kind, and source_node_id.

    Parameters
    ----------
    store:
        The ContentAddressedStore instance to write into.
    """

    def __init__(self, store: ContentAddressedStore) -> None:
        self._store = store

    @property
    def sink_name(self) -> str:
        return "artifact_store"

    def accept(self, envelope: EnvelopeBase) -> str:
        """Store the envelope as a content-addressed artifact.

        Returns the content address of the stored artifact.
        """
        data = envelope.model_dump(mode="json")
        canonical = canonical_json_bytes(data)

        artifact = self._store.store(
            canonical,
            name=f"envelope-{envelope.envelope_id}",
            artifact_type="envelope",
            metadata={
                "run_id": envelope.run_id,
                "envelope_kind": envelope.envelope_kind.value,
                "source_node_id": envelope.source_node_id,
                "destination_node_id": envelope.destination_node_id,
            },
        )

        logger.debug(
            "ArtifactStoreSink: stored envelope %s as %s",
            envelope.envelope_id,
            artifact.content_address,
        )
        return artifact.content_address

    def retrieve_envelope_bytes(self, content_address: str) -> bytes:
        """Retrieve the raw canonical JSON bytes of a stored envelope."""
        return self._store.retrieve(content_address)
