"""Plugin registry — manages the lifecycle of installed DLC plugins.

Invariant 13: Signed DLC plugins (ToolGate + SATL)
---------------------------------------------------
Every plugin must carry an Ed25519 signature that can be verified through
the crypto_bridge.  Unverified plugins are registered but flagged, and
verification status is persisted alongside the plugin entry.

The registry is a local-first JSON file stored at
``.corvusforge/plugins/registry.json``.  It is the single source of truth
for which plugins are installed, enabled, and verified.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Plugin kinds
# ---------------------------------------------------------------------------

class PluginKind(str, Enum):
    """The category of functionality a plugin provides.

    Each kind determines where in the pipeline the plugin hooks in:

    * ``stage_extension`` — adds pre/post hooks to existing pipeline stages.
    * ``sink`` — adds a new routing sink (e.g. Slack, S3).
    * ``validator`` — adds custom validation rules for stage outputs.
    * ``reporter`` — adds custom report generation.
    * ``transformer`` — adds data transformation between stages.
    """

    STAGE_EXTENSION = "stage_extension"
    SINK = "sink"
    VALIDATOR = "validator"
    REPORTER = "reporter"
    TRANSFORMER = "transformer"


# ---------------------------------------------------------------------------
# Plugin entry model
# ---------------------------------------------------------------------------

class PluginEntry(BaseModel):
    """Immutable record of a single installed plugin.

    Each entry captures the plugin's identity, its Ed25519 signature, and
    whether the signature has been verified through the crypto bridge.

    Examples
    --------
    >>> entry = PluginEntry(
    ...     name="corvusforge-slack-sink",
    ...     version="1.0.0",
    ...     kind=PluginKind.SINK,
    ...     author="CORVUSFORGE, LLC",
    ...     description="Routes envelopes to Slack channels",
    ...     entry_point="corvusforge_slack.sink:SlackSink",
    ... )
    >>> entry.verified
    False
    >>> entry.enabled
    True
    """

    model_config = ConfigDict(frozen=True)

    plugin_id: str = Field(
        default_factory=lambda: f"plg-{uuid.uuid4().hex[:12]}"
    )
    name: str
    version: str
    kind: PluginKind
    author: str
    description: str = ""
    entry_point: str  # dotted import path, e.g. "my_plugin.main:Plugin"
    signature: str = ""  # hex-encoded Ed25519 signature
    verified: bool = False
    installed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class PluginRegistry:
    """Manages the lifecycle of installed plugins.

    The registry persists to a JSON file and provides lookup, verification,
    and enable/disable operations.

    Parameters
    ----------
    registry_path:
        Path to the registry JSON file.  Created on first ``persist()``
        if it does not yet exist.

    Examples
    --------
    >>> from pathlib import Path
    >>> registry = PluginRegistry(registry_path=Path("/tmp/test_reg.json"))
    >>> entry = PluginEntry(
    ...     name="demo-plugin",
    ...     version="0.1.0",
    ...     kind=PluginKind.VALIDATOR,
    ...     author="test",
    ...     entry_point="demo:Plugin",
    ... )
    >>> pid = registry.register(entry)
    >>> registry.get("demo-plugin") is not None
    True
    """

    def __init__(
        self,
        registry_path: Path = Path(".corvusforge/plugins/registry.json"),
        *,
        plugin_trust_root_key: str = "",
    ) -> None:
        self._registry_path = registry_path
        self._plugin_trust_root_key = plugin_trust_root_key
        self._plugins: dict[str, PluginEntry] = {}
        self.load()

    # -- Registration -------------------------------------------------------

    def register(self, entry: PluginEntry) -> str:
        """Add a plugin to the registry and persist.

        Parameters
        ----------
        entry:
            The ``PluginEntry`` to register.

        Returns
        -------
        str
            The ``plugin_id`` of the registered entry.

        Raises
        ------
        ValueError
            If a plugin with the same name but a *different* version is
            already registered.  To upgrade, ``unregister`` the old version
            first.

        Examples
        --------
        >>> registry = PluginRegistry(Path("/tmp/reg.json"))
        >>> e = PluginEntry(
        ...     name="sink-x", version="1.0.0",
        ...     kind=PluginKind.SINK, author="a", entry_point="x:S",
        ... )
        >>> pid = registry.register(e)
        >>> pid.startswith("plg-")
        True
        """
        existing = self._plugins.get(entry.name)
        if existing is not None and existing.version != entry.version:
            raise ValueError(
                f"Plugin '{entry.name}' v{existing.version} is already "
                f"registered.  Unregister it before installing v{entry.version}."
            )
        self._plugins[entry.name] = entry
        self.persist()
        logger.info("Registered plugin %s v%s (%s)", entry.name, entry.version, entry.kind.value)
        return entry.plugin_id

    def unregister(self, name: str) -> bool:
        """Remove a plugin from the registry.

        Parameters
        ----------
        name:
            The plugin name to remove.

        Returns
        -------
        bool
            ``True`` if the plugin was found and removed, ``False`` otherwise.
        """
        if name in self._plugins:
            del self._plugins[name]
            self.persist()
            logger.info("Unregistered plugin '%s'.", name)
            return True
        logger.warning("Cannot unregister '%s' — not found in registry.", name)
        return False

    # -- Lookup -------------------------------------------------------------

    def get(self, name: str) -> PluginEntry | None:
        """Return the ``PluginEntry`` for *name*, or ``None`` if not found."""
        return self._plugins.get(name)

    def list_plugins(
        self,
        kind: PluginKind | None = None,
        enabled_only: bool = True,
    ) -> list[PluginEntry]:
        """Return registered plugins, optionally filtered by kind and enabled status.

        Parameters
        ----------
        kind:
            If provided, only return plugins of this ``PluginKind``.
        enabled_only:
            If ``True`` (default), exclude disabled plugins.

        Returns
        -------
        list[PluginEntry]
            Matching plugins sorted by name.
        """
        result: list[PluginEntry] = []
        for entry in self._plugins.values():
            if enabled_only and not entry.enabled:
                continue
            if kind is not None and entry.kind != kind:
                continue
            result.append(entry)
        return sorted(result, key=lambda e: e.name)

    # -- Verification -------------------------------------------------------

    def verify_plugin(self, name: str) -> bool:
        """Verify the signature of an installed plugin via the crypto bridge.

        Attempts to import ``corvusforge.bridge.crypto_bridge`` and call
        ``verify_data`` with the plugin's signature and entry-point bytes.

        **Fail-closed:** If the crypto bridge is unavailable, the plugin
        remains ``verified=False``.  If verification throws, the plugin
        remains ``verified=False``.  Only an explicit cryptographic
        confirmation sets ``verified=True``.

        Parameters
        ----------
        name:
            The plugin name to verify.

        Returns
        -------
        bool
            ``True`` only if the signature was cryptographically confirmed.
            ``False`` in all other cases (missing, unsigned, unavailable
            crypto, verification failure, or exception).
        """
        entry = self._plugins.get(name)
        if entry is None:
            logger.warning("Cannot verify '%s' — not found in registry.", name)
            return False

        if not entry.signature:
            logger.warning("Plugin '%s' has no signature — cannot verify.", name)
            return False

        try:
            from corvusforge.bridge.crypto_bridge import is_saoe_crypto_available, verify_data

            if not is_saoe_crypto_available():
                logger.warning(
                    "Crypto bridge unavailable — plugin '%s' remains unverified "
                    "(install saoe-core for production verification).",
                    name,
                )
                # Fail-closed: do NOT mark as verified.
                return False

            # Fail-closed: no configured trust root → cannot verify
            if not self._plugin_trust_root_key:
                logger.warning(
                    "No plugin trust root key configured — plugin '%s' "
                    "remains unverified (fail-closed).",
                    name,
                )
                return False

            # Build the data payload that was originally signed.
            from corvusforge.core.hasher import canonical_json_bytes

            payload = canonical_json_bytes({
                "name": entry.name,
                "version": entry.version,
                "entry_point": entry.entry_point,
            })
            # Authority comes from the configured trust root, NOT from
            # plugin-supplied metadata (which is attacker-controlled).
            valid = verify_data(payload, entry.signature, self._plugin_trust_root_key)
            updated = entry.model_copy(update={"verified": valid})
            self._plugins[name] = updated
            self.persist()
            if valid:
                logger.info("Plugin '%s' signature verified.", name)
            else:
                logger.warning("Plugin '%s' signature verification FAILED.", name)
            return valid

        except Exception:
            logger.exception(
                "Error during verification of '%s' — plugin remains unverified.",
                name,
            )
            # Fail-closed: do NOT mark as verified on exception.
            return False

    # -- Enable / Disable ---------------------------------------------------

    def enable(self, name: str) -> None:
        """Enable a plugin by name.

        Raises
        ------
        KeyError
            If the plugin is not registered.
        """
        entry = self._plugins.get(name)
        if entry is None:
            raise KeyError(f"Plugin '{name}' is not registered.")
        self._plugins[name] = entry.model_copy(update={"enabled": True})
        self.persist()
        logger.info("Enabled plugin '%s'.", name)

    def disable(self, name: str) -> None:
        """Disable a plugin by name.

        Raises
        ------
        KeyError
            If the plugin is not registered.
        """
        entry = self._plugins.get(name)
        if entry is None:
            raise KeyError(f"Plugin '{name}' is not registered.")
        self._plugins[name] = entry.model_copy(update={"enabled": False})
        self.persist()
        logger.info("Disabled plugin '%s'.", name)

    # -- Persistence --------------------------------------------------------

    def persist(self) -> None:
        """Write the registry to its JSON file.

        Creates parent directories as needed.
        """
        self._registry_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            name: json.loads(entry.model_dump_json())
            for name, entry in self._plugins.items()
        }
        self._registry_path.write_text(
            json.dumps(data, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        logger.debug("Persisted plugin registry to %s.", self._registry_path)

    def load(self) -> None:
        """Load the registry from its JSON file, if it exists."""
        if not self._registry_path.exists():
            logger.debug("No registry file at %s — starting fresh.", self._registry_path)
            return
        try:
            raw = json.loads(self._registry_path.read_text(encoding="utf-8"))
            for name, entry_data in raw.items():
                self._plugins[name] = PluginEntry(**entry_data)
            logger.info("Loaded %d plugin(s) from registry.", len(self._plugins))
        except Exception:
            logger.exception("Failed to load plugin registry from %s.", self._registry_path)

    # -- Stats --------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return summary statistics about the registry.

        Returns
        -------
        dict[str, Any]
            Keys: ``total``, ``verified_count``, ``enabled_count``, and
            a ``by_kind`` dict mapping each ``PluginKind`` value to its count.

        Examples
        --------
        >>> registry = PluginRegistry(Path("/tmp/stats_reg.json"))
        >>> stats = registry.get_stats()
        >>> stats["total"]
        0
        """
        by_kind: dict[str, int] = {k.value: 0 for k in PluginKind}
        verified = 0
        enabled = 0
        for entry in self._plugins.values():
            by_kind[entry.kind.value] += 1
            if entry.verified:
                verified += 1
            if entry.enabled:
                enabled += 1
        return {
            "total": len(self._plugins),
            "verified_count": verified,
            "enabled_count": enabled,
            "by_kind": by_kind,
        }
