"""DLC package loader — reads, verifies, and installs DLC plugin packages.

Invariant 13: Signed DLC plugins (ToolGate + SATL)
---------------------------------------------------
Each DLC package is a directory with this structure::

    {name}-{version}/
        manifest.json    — plugin metadata and entry-point declaration
        plugin.py        — the plugin implementation module
        signature.sig    — Ed25519 signature over the manifest hash

The loader validates the manifest, computes a content hash of all package
files, and verifies the signature through the crypto bridge before creating
a ``PluginEntry`` in the registry.
"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from corvusforge.core.hasher import canonical_json_bytes, sha256_hex
from corvusforge.plugins.registry import PluginEntry, PluginKind, PluginRegistry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DLC models
# ---------------------------------------------------------------------------

class DLCManifest(BaseModel):
    """Schema for a DLC package's ``manifest.json``.

    The manifest declares the plugin's identity, entry point, kind, and
    minimum Corvusforge version required to load it.

    Examples
    --------
    >>> manifest = DLCManifest(
    ...     name="corvusforge-s3-sink",
    ...     version="1.0.0",
    ...     author="CORVUSFORGE, LLC",
    ...     description="S3 artifact routing sink",
    ...     entry_point="corvusforge_s3.sink:S3Sink",
    ...     kind=PluginKind.SINK,
    ... )
    >>> manifest.min_corvusforge_version
    '0.2.0'
    """

    model_config = ConfigDict(frozen=True)

    name: str
    version: str
    author: str
    description: str = ""
    entry_point: str  # dotted import path, e.g. "my_plugin.main:Plugin"
    kind: PluginKind
    dependencies: list[str] = Field(default_factory=list)
    min_corvusforge_version: str = "0.2.0"


class DLCPackage(BaseModel):
    """Immutable record of a loaded DLC package.

    Captures the package identity, the hash of its manifest, the Ed25519
    signature, and a map of every file in the package to its content hash.

    Examples
    --------
    >>> pkg = DLCPackage(
    ...     name="demo-dlc",
    ...     version="0.1.0",
    ...     author="test",
    ...     description="Demo DLC package",
    ...     manifest_hash="abc123",
    ...     signature="",
    ...     files={"manifest.json": "aaa", "plugin.py": "bbb"},
    ... )
    >>> len(pkg.files)
    2
    """

    model_config = ConfigDict(frozen=True)

    package_id: str = Field(
        default_factory=lambda: f"dlc-{uuid.uuid4().hex[:12]}"
    )
    name: str
    version: str
    author: str
    description: str = ""
    manifest_hash: str
    signature: str
    files: dict[str, str] = Field(default_factory=dict)  # relative_path -> content_hash
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

class PluginLoader:
    """Loads, verifies, and installs DLC plugin packages.

    Parameters
    ----------
    plugins_dir:
        Base directory where installed DLC packages are stored.
    registry:
        Optional ``PluginRegistry`` instance.  When provided, loaded
        plugins are automatically registered.

    Examples
    --------
    >>> from pathlib import Path
    >>> loader = PluginLoader(plugins_dir=Path("/tmp/cf_plugins"))
    >>> loader.list_installed()
    []
    """

    def __init__(
        self,
        plugins_dir: Path = Path(".corvusforge/plugins/installed/"),
        registry: PluginRegistry | None = None,
    ) -> None:
        self._plugins_dir = plugins_dir
        self._plugins_dir.mkdir(parents=True, exist_ok=True)
        self._registry = registry

    # -- Public API ---------------------------------------------------------

    def load_dlc(self, package_path: Path) -> PluginEntry:
        """Load a DLC package from disk and optionally register it.

        Reads the manifest, computes the manifest hash, verifies the
        package signature (if the crypto bridge is available), and creates
        a ``PluginEntry``.

        Parameters
        ----------
        package_path:
            Path to the DLC package directory (containing ``manifest.json``,
            ``plugin.py``, and ``signature.sig``).

        Returns
        -------
        PluginEntry
            The created entry, registered if a ``PluginRegistry`` was provided.

        Raises
        ------
        FileNotFoundError
            If the package directory or manifest does not exist.
        ValueError
            If the manifest fails validation.

        Examples
        --------
        >>> # Assuming a valid DLC directory at /tmp/my-plugin-1.0.0/
        >>> loader = PluginLoader(plugins_dir=Path("/tmp/installed"))
        >>> # entry = loader.load_dlc(Path("/tmp/my-plugin-1.0.0"))
        """
        manifest = self._read_manifest(package_path)
        manifest_hash = self._compute_manifest_hash(package_path)

        # Read signature if present
        sig_path = package_path / "signature.sig"
        signature = ""
        if sig_path.exists():
            signature = sig_path.read_text(encoding="utf-8").strip()

        # Compute per-file content hashes
        files: dict[str, str] = {}
        for file_path in sorted(package_path.rglob("*")):
            if file_path.is_file():
                rel = str(file_path.relative_to(package_path))
                content_bytes = file_path.read_bytes()
                files[rel] = sha256_hex(content_bytes)

        # Verify signature
        verified = self.verify_dlc(package_path)

        entry = PluginEntry(
            name=manifest.name,
            version=manifest.version,
            kind=manifest.kind,
            author=manifest.author,
            description=manifest.description,
            entry_point=manifest.entry_point,
            signature=signature,
            verified=verified,
            metadata={
                "manifest_hash": manifest_hash,
                "dependencies": manifest.dependencies,
                "min_corvusforge_version": manifest.min_corvusforge_version,
                "files": files,
            },
        )

        if self._registry is not None:
            self._registry.register(entry)
            logger.info(
                "Loaded and registered DLC '%s' v%s.", manifest.name, manifest.version
            )
        else:
            logger.info(
                "Loaded DLC '%s' v%s (no registry — not registered).",
                manifest.name,
                manifest.version,
            )

        return entry

    def verify_dlc(self, package_path: Path) -> bool:
        """Verify the cryptographic signature of a DLC package.

        Computes the manifest hash and checks it against the signature in
        ``signature.sig`` using the crypto bridge.

        **Fail-closed:** If the crypto bridge is unavailable or verification
        throws, the package remains unverified.  Only an explicit
        cryptographic confirmation returns ``True``.

        Parameters
        ----------
        package_path:
            Path to the DLC package directory.

        Returns
        -------
        bool
            ``True`` only if the signature was cryptographically confirmed.
            ``False`` in all other cases.
        """
        sig_path = package_path / "signature.sig"
        if not sig_path.exists():
            logger.warning(
                "No signature.sig in '%s' — cannot verify.", package_path
            )
            return False

        signature = sig_path.read_text(encoding="utf-8").strip()
        if not signature:
            logger.warning("Empty signature in '%s'.", package_path)
            return False

        manifest_hash = self._compute_manifest_hash(package_path)
        manifest_bytes = manifest_hash.encode("utf-8")

        try:
            from corvusforge.bridge.crypto_bridge import (
                is_saoe_crypto_available,
                verify_data,
            )

            if not is_saoe_crypto_available():
                logger.warning(
                    "Crypto bridge unavailable — DLC '%s' remains unverified "
                    "(install saoe-core for production verification).",
                    package_path.name,
                )
                # Fail-closed: do NOT assume valid.
                return False

            # In a full deployment, the public key comes from the DLC manifest
            # or a ToolGate key registry.  Here we read it from the manifest
            # metadata or fall back to an empty string (verification will fail).
            manifest = self._read_manifest(package_path)
            public_key = ""  # Populated from ToolGate in production
            valid = verify_data(manifest_bytes, signature, public_key)
            if valid:
                logger.info("DLC '%s' signature verified.", package_path.name)
            else:
                logger.warning(
                    "DLC '%s' signature verification FAILED.", package_path.name
                )
            return valid

        except Exception:
            logger.exception(
                "Error verifying DLC '%s' — package remains unverified.",
                package_path.name,
            )
            # Fail-closed: do NOT assume valid on exception.
            return False

    def install_dlc(self, package_path: Path) -> PluginEntry:
        """Copy a DLC package to the plugins directory and load it.

        Parameters
        ----------
        package_path:
            Path to the source DLC package directory.

        Returns
        -------
        PluginEntry
            The entry for the newly installed plugin.

        Raises
        ------
        FileNotFoundError
            If the source package directory does not exist.

        Examples
        --------
        >>> loader = PluginLoader(plugins_dir=Path("/tmp/installed"))
        >>> # entry = loader.install_dlc(Path("/tmp/my-plugin-1.0.0"))
        """
        if not package_path.is_dir():
            raise FileNotFoundError(
                f"DLC package directory not found: {package_path}"
            )

        dest = self._plugins_dir / package_path.name
        if dest.exists():
            logger.info(
                "Overwriting existing installation at '%s'.", dest
            )
            shutil.rmtree(dest)

        shutil.copytree(package_path, dest)
        logger.info("Installed DLC package to '%s'.", dest)
        return self.load_dlc(dest)

    def list_installed(self) -> list[Path]:
        """List paths to all installed DLC package directories.

        Returns
        -------
        list[Path]
            Sorted list of directories under the plugins installation path.

        Examples
        --------
        >>> loader = PluginLoader(plugins_dir=Path("/tmp/empty_plugins"))
        >>> loader.list_installed()
        []
        """
        if not self._plugins_dir.exists():
            return []
        return sorted(
            p for p in self._plugins_dir.iterdir()
            if p.is_dir() and (p / "manifest.json").exists()
        )

    # -- Internal helpers ---------------------------------------------------

    def _read_manifest(self, package_path: Path) -> DLCManifest:
        """Read and validate ``manifest.json`` from a DLC package directory.

        Parameters
        ----------
        package_path:
            Path to the DLC package directory.

        Returns
        -------
        DLCManifest
            The parsed and validated manifest.

        Raises
        ------
        FileNotFoundError
            If ``manifest.json`` does not exist.
        ValueError
            If the manifest is malformed or fails validation.
        """
        manifest_path = package_path / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(
                f"No manifest.json in DLC package: {package_path}"
            )

        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            return DLCManifest(**raw)
        except Exception as exc:
            raise ValueError(
                f"Invalid manifest.json in '{package_path}': {exc}"
            ) from exc

    def _compute_manifest_hash(self, package_path: Path) -> str:
        """Compute a content hash over all files in the DLC package.

        Uses ``corvusforge.core.hasher.sha256_hex`` on the canonical JSON
        representation of a sorted mapping of ``{relative_path: file_hash}``.

        Parameters
        ----------
        package_path:
            Path to the DLC package directory.

        Returns
        -------
        str
            The SHA-256 hex digest of the package contents.
        """
        file_hashes: dict[str, str] = {}
        for file_path in sorted(package_path.rglob("*")):
            if file_path.is_file() and file_path.name != "signature.sig":
                rel = str(file_path.relative_to(package_path))
                file_hashes[rel] = sha256_hex(file_path.read_bytes())

        return sha256_hex(canonical_json_bytes(file_hashes))
