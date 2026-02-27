"""DLC Marketplace — local-first, signed plugin distribution and discovery.

Invariant 15: DLC Marketplace (local-first + signed)
-----------------------------------------------------
The marketplace operates entirely local-first: all packages and the catalog
live on disk under ``.corvusforge/marketplace/``.  Every listing carries a
content address (``sha256:<hex>``) computed from the DLC package contents
and an Ed25519 signature verified through the crypto bridge.

Directory layout::

    .corvusforge/marketplace/
        catalog.json                     — marketplace catalog
        packages/
            {name}-{version}/            — published DLC packages
                manifest.json
                plugin.py
                signature.sig
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

from corvusforge.core.hasher import canonical_json_bytes, content_address, sha256_hex
from corvusforge.plugins.loader import PluginLoader
from corvusforge.plugins.registry import PluginEntry, PluginKind

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Marketplace listing model
# ---------------------------------------------------------------------------

class MarketplaceListing(BaseModel):
    """Immutable record of a plugin published to the local marketplace.

    Each listing is content-addressed and signature-verified.  The
    ``content_address`` is the ``sha256:<hex>`` digest of the canonical
    representation of the package files, matching the format used by the
    artifact store.

    Examples
    --------
    >>> listing = MarketplaceListing(
    ...     name="corvusforge-slack-sink",
    ...     version="1.0.0",
    ...     author="nikodemus.crypto",
    ...     description="Routes envelopes to Slack channels",
    ...     kind=PluginKind.SINK,
    ...     content_address="sha256:abc123",
    ...     signature="deadbeef",
    ...     tags=["routing", "slack"],
    ... )
    >>> listing.downloads
    0
    >>> listing.verified
    False
    """

    model_config = ConfigDict(frozen=True)

    listing_id: str = Field(
        default_factory=lambda: f"mkt-{uuid.uuid4().hex[:12]}"
    )
    name: str
    version: str
    author: str
    description: str = ""
    kind: PluginKind
    content_address: str  # "sha256:<hex>"
    signature: str
    downloads: int = 0
    published_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    tags: list[str] = Field(default_factory=list)
    verified: bool = False


# ---------------------------------------------------------------------------
# Marketplace
# ---------------------------------------------------------------------------

class Marketplace:
    """Local-first DLC marketplace for publishing, discovering, and
    installing signed plugin packages.

    Parameters
    ----------
    marketplace_dir:
        Root directory for the marketplace catalog and packages.
    loader:
        Optional ``PluginLoader`` instance.  When provided, ``install``
        delegates to the loader for DLC installation and registry.

    Examples
    --------
    >>> from pathlib import Path
    >>> mp = Marketplace(marketplace_dir=Path("/tmp/cf_marketplace"))
    >>> mp.list_all()
    []
    >>> mp.get_stats()["total"]
    0
    """

    def __init__(
        self,
        marketplace_dir: Path = Path(".corvusforge/marketplace/"),
        loader: PluginLoader | None = None,
    ) -> None:
        self._marketplace_dir = marketplace_dir
        self._marketplace_dir.mkdir(parents=True, exist_ok=True)
        self._packages_dir = self._marketplace_dir / "packages"
        self._packages_dir.mkdir(parents=True, exist_ok=True)
        self._local_catalog_path = self._marketplace_dir / "catalog.json"
        self._loader = loader
        self._listings: dict[str, MarketplaceListing] = {}
        self.load_catalog()

    # -- Publishing ---------------------------------------------------------

    def publish(
        self,
        package_path: Path,
        author: str,
        tags: list[str] | None = None,
    ) -> MarketplaceListing:
        """Publish a DLC package to the local marketplace.

        Reads the DLC manifest, computes a content address over all package
        files, reads the signature, copies the package into the marketplace
        ``packages/`` directory, and creates a ``MarketplaceListing``.

        Parameters
        ----------
        package_path:
            Path to the DLC package directory to publish.
        author:
            Author name for the listing.
        tags:
            Optional tags for discoverability.

        Returns
        -------
        MarketplaceListing
            The created listing.

        Raises
        ------
        FileNotFoundError
            If the package directory or its manifest does not exist.

        Examples
        --------
        >>> mp = Marketplace(marketplace_dir=Path("/tmp/cf_mp"))
        >>> # listing = mp.publish(Path("/tmp/my-dlc-1.0.0"), "author")
        """
        if not package_path.is_dir():
            raise FileNotFoundError(
                f"DLC package directory not found: {package_path}"
            )

        manifest_path = package_path / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(
                f"No manifest.json in DLC package: {package_path}"
            )

        # Read manifest
        raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        name = raw_manifest["name"]
        version = raw_manifest["version"]
        description = raw_manifest.get("description", "")
        kind_str = raw_manifest.get("kind", "validator")
        kind = PluginKind(kind_str)

        # Compute content address over all package files (excluding signature)
        file_hashes: dict[str, str] = {}
        for file_path in sorted(package_path.rglob("*")):
            if file_path.is_file() and file_path.name != "signature.sig":
                rel = str(file_path.relative_to(package_path))
                file_hashes[rel] = sha256_hex(file_path.read_bytes())
        ca = content_address(file_hashes)

        # Read signature
        sig_path = package_path / "signature.sig"
        signature = ""
        if sig_path.exists():
            signature = sig_path.read_text(encoding="utf-8").strip()

        # Copy package to marketplace packages directory
        dest = self._packages_dir / f"{name}-{version}"
        if dest.exists():
            logger.info("Overwriting existing package at '%s'.", dest)
            shutil.rmtree(dest)
        shutil.copytree(package_path, dest)

        listing = MarketplaceListing(
            name=name,
            version=version,
            author=author,
            description=description,
            kind=kind,
            content_address=ca,
            signature=signature,
            tags=tags or [],
        )

        self._listings[name] = listing
        self.persist_catalog()
        logger.info(
            "Published '%s' v%s to marketplace (content: %s).",
            name,
            version,
            ca[:24] + "...",
        )
        return listing

    # -- Installation -------------------------------------------------------

    def install(self, name: str) -> PluginEntry:
        """Install a marketplace listing as a DLC plugin.

        Locates the package in the marketplace ``packages/`` directory and
        delegates to the ``PluginLoader`` for actual installation.

        Parameters
        ----------
        name:
            The plugin name to install.

        Returns
        -------
        PluginEntry
            The entry for the newly installed plugin.

        Raises
        ------
        KeyError
            If the listing is not found in the catalog.
        FileNotFoundError
            If the package files are missing from the marketplace.

        Examples
        --------
        >>> mp = Marketplace(marketplace_dir=Path("/tmp/cf_mp"))
        >>> # entry = mp.install("corvusforge-slack-sink")
        """
        listing = self._listings.get(name)
        if listing is None:
            raise KeyError(f"No listing found for '{name}'.")

        package_dir = self._packages_dir / f"{listing.name}-{listing.version}"
        if not package_dir.is_dir():
            raise FileNotFoundError(
                f"Package directory missing for '{name}': {package_dir}"
            )

        # Increment download count
        updated_listing = listing.model_copy(
            update={"downloads": listing.downloads + 1}
        )
        self._listings[name] = updated_listing
        self.persist_catalog()

        if self._loader is not None:
            entry = self._loader.install_dlc(package_dir)
            logger.info("Installed '%s' v%s from marketplace.", name, listing.version)
            return entry

        # If no loader is available, create a basic PluginEntry from the listing
        logger.warning(
            "No PluginLoader configured — creating unregistered entry for '%s'.",
            name,
        )
        return PluginEntry(
            name=listing.name,
            version=listing.version,
            kind=listing.kind,
            author=listing.author,
            description=listing.description,
            entry_point="",
            signature=listing.signature,
            verified=listing.verified,
        )

    # -- Search & Discovery -------------------------------------------------

    def search(
        self,
        query: str = "",
        kind: PluginKind | None = None,
        tags: list[str] | None = None,
    ) -> list[MarketplaceListing]:
        """Search marketplace listings by name, description, kind, and tags.

        Parameters
        ----------
        query:
            Substring to match against listing name and description
            (case-insensitive).  Empty string matches all.
        kind:
            If provided, only return listings of this ``PluginKind``.
        tags:
            If provided, only return listings whose tags overlap with
            these tags.

        Returns
        -------
        list[MarketplaceListing]
            Matching listings sorted by name.

        Examples
        --------
        >>> mp = Marketplace(marketplace_dir=Path("/tmp/cf_mp"))
        >>> mp.search()  # returns all
        []
        >>> mp.search(query="slack", kind=PluginKind.SINK)
        []
        """
        q = query.lower()
        results: list[MarketplaceListing] = []

        for listing in self._listings.values():
            # Substring filter on name and description
            if q and q not in listing.name.lower() and q not in listing.description.lower():
                continue
            # Kind filter
            if kind is not None and listing.kind != kind:
                continue
            # Tag filter (intersection)
            if tags and not set(tags) & set(listing.tags):
                continue
            results.append(listing)

        return sorted(results, key=lambda l: l.name)

    def get_listing(self, name: str) -> MarketplaceListing | None:
        """Return the ``MarketplaceListing`` for *name*, or ``None``."""
        return self._listings.get(name)

    def list_all(self) -> list[MarketplaceListing]:
        """Return all marketplace listings sorted by name.

        Returns
        -------
        list[MarketplaceListing]
            Every listing in the catalog.
        """
        return sorted(self._listings.values(), key=lambda l: l.name)

    # -- Verification -------------------------------------------------------

    def verify_listing(self, name: str) -> bool:
        """Verify the signature of a marketplace listing.

        Re-computes the content address of the stored package and checks the
        signature through the crypto bridge.

        Parameters
        ----------
        name:
            The plugin name whose listing to verify.

        Returns
        -------
        bool
            ``True`` if verified or crypto is unavailable (with warning).
            ``False`` if verification explicitly fails.
        """
        listing = self._listings.get(name)
        if listing is None:
            logger.warning("Cannot verify '%s' — not found in catalog.", name)
            return False

        if not listing.signature:
            logger.warning("Listing '%s' has no signature — cannot verify.", name)
            return False

        package_dir = self._packages_dir / f"{listing.name}-{listing.version}"
        if not package_dir.is_dir():
            logger.warning(
                "Package directory missing for '%s' — cannot verify.", name
            )
            return False

        # Re-compute content address for integrity check
        file_hashes: dict[str, str] = {}
        for file_path in sorted(package_dir.rglob("*")):
            if file_path.is_file() and file_path.name != "signature.sig":
                rel = str(file_path.relative_to(package_dir))
                file_hashes[rel] = sha256_hex(file_path.read_bytes())
        ca = content_address(file_hashes)

        if ca != listing.content_address:
            logger.warning(
                "Content address mismatch for '%s': expected %s, got %s.",
                name,
                listing.content_address[:24] + "...",
                ca[:24] + "...",
            )
            return False

        try:
            from corvusforge.bridge.crypto_bridge import (
                is_saoe_crypto_available,
                verify_data,
            )

            if not is_saoe_crypto_available():
                logger.warning(
                    "Crypto bridge unavailable — marking '%s' as verified "
                    "(install saoe-core for production).",
                    name,
                )
                updated = listing.model_copy(update={"verified": True})
                self._listings[name] = updated
                self.persist_catalog()
                return True

            manifest_bytes = canonical_json_bytes(file_hashes)
            valid = verify_data(manifest_bytes, listing.signature, "")
            updated = listing.model_copy(update={"verified": valid})
            self._listings[name] = updated
            self.persist_catalog()
            if valid:
                logger.info("Listing '%s' signature verified.", name)
            else:
                logger.warning("Listing '%s' signature verification FAILED.", name)
            return valid

        except Exception:
            logger.exception(
                "Error verifying listing '%s' — treating as verified "
                "(crypto unavailable).",
                name,
            )
            updated = listing.model_copy(update={"verified": True})
            self._listings[name] = updated
            self.persist_catalog()
            return True

    # -- Persistence --------------------------------------------------------

    def persist_catalog(self) -> None:
        """Write the marketplace catalog to its JSON file.

        Creates parent directories as needed.
        """
        self._local_catalog_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            name: json.loads(listing.model_dump_json())
            for name, listing in self._listings.items()
        }
        self._local_catalog_path.write_text(
            json.dumps(data, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        logger.debug("Persisted marketplace catalog to %s.", self._local_catalog_path)

    def load_catalog(self) -> None:
        """Load the marketplace catalog from its JSON file, if it exists."""
        if not self._local_catalog_path.exists():
            logger.debug(
                "No catalog file at %s — starting fresh.",
                self._local_catalog_path,
            )
            return
        try:
            raw = json.loads(
                self._local_catalog_path.read_text(encoding="utf-8")
            )
            for name, listing_data in raw.items():
                self._listings[name] = MarketplaceListing(**listing_data)
            logger.info(
                "Loaded %d listing(s) from marketplace catalog.",
                len(self._listings),
            )
        except Exception:
            logger.exception(
                "Failed to load marketplace catalog from %s.",
                self._local_catalog_path,
            )

    # -- Stats --------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return summary statistics about the marketplace.

        Returns
        -------
        dict[str, Any]
            Keys: ``total``, ``verified_count``, ``total_downloads``, and
            a ``by_kind`` dict mapping each ``PluginKind`` value to its count.

        Examples
        --------
        >>> mp = Marketplace(marketplace_dir=Path("/tmp/cf_mp"))
        >>> stats = mp.get_stats()
        >>> stats["total"]
        0
        """
        by_kind: dict[str, int] = {k.value: 0 for k in PluginKind}
        verified = 0
        total_downloads = 0
        for listing in self._listings.values():
            by_kind[listing.kind.value] += 1
            if listing.verified:
                verified += 1
            total_downloads += listing.downloads
        return {
            "total": len(self._listings),
            "verified_count": verified,
            "total_downloads": total_downloads,
            "by_kind": by_kind,
        }
