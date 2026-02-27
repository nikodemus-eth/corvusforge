"""Tests for ContentAddressedStore — immutability, integrity, content addressing."""

from __future__ import annotations

import pytest

from corvusforge.core.artifact_store import (
    ContentAddressedStore,
    ArtifactIntegrityError,
)
from corvusforge.core.hasher import sha256_hex


class TestContentAddressedStore:
    def test_store_and_retrieve(self, artifact_store: ContentAddressedStore):
        data = b"hello corvusforge"
        artifact = artifact_store.store(data, name="test.txt")
        assert artifact.content_address.startswith("sha256:")
        assert artifact.size_bytes == len(data)
        retrieved = artifact_store.retrieve(artifact.content_address)
        assert retrieved == data

    def test_content_addressing(self, artifact_store: ContentAddressedStore):
        data = b"deterministic content"
        expected_hash = sha256_hex(data)
        artifact = artifact_store.store(data)
        assert artifact.content_address == f"sha256:{expected_hash}"

    def test_idempotent_store(self, artifact_store: ContentAddressedStore):
        data = b"store me twice"
        a1 = artifact_store.store(data, name="first")
        a2 = artifact_store.store(data, name="second")
        assert a1.content_address == a2.content_address

    def test_exists(self, artifact_store: ContentAddressedStore):
        data = b"check existence"
        artifact = artifact_store.store(data)
        assert artifact_store.exists(artifact.content_address) is True
        assert artifact_store.exists("sha256:nonexistent") is False

    def test_verify_valid(self, artifact_store: ContentAddressedStore):
        data = b"verify me"
        artifact = artifact_store.store(data)
        assert artifact_store.verify(artifact.content_address) is True

    def test_retrieve_nonexistent(self, artifact_store: ContentAddressedStore):
        with pytest.raises(FileNotFoundError):
            artifact_store.retrieve("sha256:0000000000000000")

    def test_verify_nonexistent(self, artifact_store: ContentAddressedStore):
        assert artifact_store.verify("sha256:nonexistent") is False

    def test_make_ref(self, artifact_store: ContentAddressedStore):
        data = b"ref test"
        artifact = artifact_store.store(data, name="ref.dat", artifact_type="test")
        ref = artifact_store.make_ref(
            artifact.content_address, name="ref.dat", artifact_type="test"
        )
        assert ref.content_address == artifact.content_address
        assert ref.name == "ref.dat"
        assert ref.size_bytes == len(data)
