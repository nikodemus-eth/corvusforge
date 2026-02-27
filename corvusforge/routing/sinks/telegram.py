"""Telegram notification sink — builds Telegram notification payloads (stub).

This module constructs Telegram Bot API-compatible message payloads from
Corvusforge envelopes.  Actual HTTP delivery is deferred to the caller
or a transport layer; this sink only builds the payload.

Requires a ``chat_id`` and optional ``bot_token`` in the sink configuration.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict

from corvusforge.models.envelopes import EnvelopeBase

logger = logging.getLogger(__name__)


class TelegramPayload(BaseModel):
    """A Telegram Bot API sendMessage payload."""

    model_config = ConfigDict(frozen=True)

    chat_id: str
    text: str
    parse_mode: str = "HTML"
    disable_web_page_preview: bool = True


class TelegramSink:
    """Builds Telegram notification payloads from envelopes (stub).

    This sink does NOT send HTTP requests.  It constructs the payload and
    stores it in a buffer for later retrieval by a transport layer or test
    harness.

    Parameters
    ----------
    chat_id:
        The Telegram chat ID to send notifications to.
    bot_token:
        The Telegram bot token (stored but not used in this stub).
    """

    def __init__(self, chat_id: str, bot_token: str = "") -> None:
        self._chat_id = chat_id
        self._bot_token = bot_token
        self._pending_payloads: list[TelegramPayload] = []

    @property
    def sink_name(self) -> str:
        return "telegram"

    def accept(self, envelope: EnvelopeBase) -> None:
        """Build a Telegram notification payload from the envelope.

        The payload is appended to the pending buffer but NOT sent.
        Call ``flush()`` to retrieve and clear pending payloads.
        """
        text = self._format_message(envelope)
        payload = TelegramPayload(
            chat_id=self._chat_id,
            text=text,
        )
        self._pending_payloads.append(payload)
        logger.debug(
            "TelegramSink: queued notification for envelope %s",
            envelope.envelope_id,
        )

    def flush(self) -> list[TelegramPayload]:
        """Return and clear all pending payloads."""
        payloads = list(self._pending_payloads)
        self._pending_payloads.clear()
        return payloads

    @property
    def pending_count(self) -> int:
        """Return the number of pending payloads."""
        return len(self._pending_payloads)

    @staticmethod
    def _format_message(envelope: EnvelopeBase) -> str:
        """Format an envelope into a human-readable Telegram message."""
        kind = envelope.envelope_kind.value.replace("_", " ").title()
        stage_id = getattr(envelope, "stage_id", None) or "N/A"
        details: list[str] = [
            f"<b>Corvusforge {kind}</b>",
            f"Run: <code>{envelope.run_id}</code>",
            f"Stage: <code>{stage_id}</code>",
            f"Source: {envelope.source_node_id}",
        ]

        # Add kind-specific details
        if hasattr(envelope, "event_type"):
            details.append(f"Event: {envelope.event_type}")
        if hasattr(envelope, "error_message"):
            details.append(f"Error: {envelope.error_message}")
        if hasattr(envelope, "question"):
            details.append(f"Question: {envelope.question}")

        details.append(f"Time: {envelope.timestamp_utc.isoformat()}")
        return "\n".join(details)

    def build_api_url(self) -> str:
        """Return the Telegram Bot API sendMessage URL (stub).

        Returns an empty string if no bot_token is configured.
        """
        if not self._bot_token:
            return ""
        return f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
