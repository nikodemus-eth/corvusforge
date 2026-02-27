"""Email notification sink — builds email notification payloads (stub).

This module constructs email-compatible message payloads from Corvusforge
envelopes.  Actual SMTP delivery is deferred to the caller or a transport
layer; this sink only builds the payload.

Requires a ``recipient`` email address in the sink configuration.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict

from corvusforge.models.envelopes import EnvelopeBase
from corvusforge.routing.sinks._formatting import (
    extract_detail_lines,
    extract_stage_id,
    format_kind_label,
)

logger = logging.getLogger(__name__)


class EmailPayload(BaseModel):
    """An email notification payload ready for SMTP delivery."""

    model_config = ConfigDict(frozen=True)

    recipient: str
    sender: str
    subject: str
    body_text: str
    body_html: str = ""
    reply_to: str = ""
    headers: dict[str, str] = {}


class EmailSink:
    """Builds email notification payloads from envelopes (stub).

    This sink does NOT send emails.  It constructs the payload and stores
    it in a buffer for later retrieval by a transport layer or test harness.

    Parameters
    ----------
    recipient:
        The email address to send notifications to.
    sender:
        The sender address.  Defaults to ``corvusforge@localhost``.
    """

    def __init__(
        self,
        recipient: str,
        sender: str = "corvusforge@localhost",
    ) -> None:
        self._recipient = recipient
        self._sender = sender
        self._pending_payloads: list[EmailPayload] = []

    @property
    def sink_name(self) -> str:
        return "email"

    def accept(self, envelope: EnvelopeBase) -> None:
        """Build an email notification payload from the envelope.

        The payload is appended to the pending buffer but NOT sent.
        Call ``flush()`` to retrieve and clear pending payloads.
        """
        subject = self._format_subject(envelope)
        body_text = self._format_body_text(envelope)
        body_html = self._format_body_html(envelope)

        payload = EmailPayload(
            recipient=self._recipient,
            sender=self._sender,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            headers={
                "X-Corvusforge-Run-Id": envelope.run_id,
                "X-Corvusforge-Envelope-Id": envelope.envelope_id,
                "X-Corvusforge-Envelope-Kind": envelope.envelope_kind.value,
            },
        )
        self._pending_payloads.append(payload)
        logger.debug(
            "EmailSink: queued notification for envelope %s",
            envelope.envelope_id,
        )

    def flush(self) -> list[EmailPayload]:
        """Return and clear all pending payloads."""
        payloads = list(self._pending_payloads)
        self._pending_payloads.clear()
        return payloads

    @property
    def pending_count(self) -> int:
        """Return the number of pending payloads."""
        return len(self._pending_payloads)

    @staticmethod
    def _format_subject(envelope: EnvelopeBase) -> str:
        """Build the email subject line."""
        kind = format_kind_label(envelope)
        stage_id = extract_stage_id(envelope, default="general")
        return f"[Corvusforge] {kind} — {envelope.run_id} / {stage_id}"

    @staticmethod
    def _format_body_text(envelope: EnvelopeBase) -> str:
        """Build the plain-text email body."""
        kind = format_kind_label(envelope)
        stage_id = extract_stage_id(envelope)
        lines: list[str] = [
            f"Corvusforge {kind}",
            "=" * 40,
            f"Run ID:    {envelope.run_id}",
            f"Stage:     {stage_id}",
            f"Source:    {envelope.source_node_id}",
            f"Dest:      {envelope.destination_node_id}",
            f"Timestamp: {envelope.timestamp_utc.isoformat()}",
            "",
        ]

        # Kind-specific detail lines (event_type, error_message, etc.)
        detail_lines = extract_detail_lines(envelope)
        # Preserve the "Clarification:" label for email (differs from generic)
        for dl in detail_lines:
            if dl.startswith("Question:"):
                dl = dl.replace("Question:", "Clarification:", 1)
            lines.append(dl)

        lines.append("")
        lines.append("-- Corvusforge Pipeline Notification")
        return "\n".join(lines)

    @staticmethod
    def _format_body_html(envelope: EnvelopeBase) -> str:
        """Build the HTML email body."""
        kind = format_kind_label(envelope)
        stage_id = extract_stage_id(envelope)
        rows: list[str] = [
            f"<tr><td><b>Run ID</b></td><td><code>{envelope.run_id}</code></td></tr>",
            f"<tr><td><b>Stage</b></td><td><code>{stage_id}</code></td></tr>",
            f"<tr><td><b>Source</b></td><td>{envelope.source_node_id}</td></tr>",
            f"<tr><td><b>Timestamp</b></td><td>{envelope.timestamp_utc.isoformat()}</td></tr>",
        ]

        if hasattr(envelope, "event_type"):
            rows.append(f"<tr><td><b>Event</b></td><td>{envelope.event_type}</td></tr>")
        if hasattr(envelope, "error_message"):
            rows.append(f"<tr><td><b>Error</b></td><td>{envelope.error_message}</td></tr>")

        table = "\n".join(rows)
        return (
            f"<h2>Corvusforge {kind}</h2>\n"
            f"<table>\n{table}\n</table>\n"
            f"<hr/><p><em>Corvusforge Pipeline Notification</em></p>"
        )
