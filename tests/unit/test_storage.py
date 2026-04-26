"""Unit tests for the storage layer — URI parsing and in-memory fake.

S3ObjectStore requires a live MinIO/S3 and is exercised by the integration
tests in tests/integration/test_api_pipeline.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mos.storage import InMemoryObjectStore, ObjectStore, parse_s3_uri, s3_uri


class TestUriHelpers:
    def test_build(self):
        assert s3_uri("b", "k/1") == "s3://b/k/1"

    def test_parse(self):
        assert parse_s3_uri("s3://b/k/1") == ("b", "k/1")

    def test_round_trip(self):
        for bucket, key in [("a", "b.stl"), ("mos", "jobs/123/cad/a.step")]:
            assert parse_s3_uri(s3_uri(bucket, key)) == (bucket, key)

    @pytest.mark.parametrize(
        "bad",
        [
            "http://example.com/x",
            "s3://",
            "s3://bucket",
            "s3:///key",
            "s3://bucket/",
        ],
    )
    def test_rejects_bad_uri(self, bad: str):
        with pytest.raises(ValueError):
            parse_s3_uri(bad)

    def test_build_rejects_empty(self):
        with pytest.raises(ValueError):
            s3_uri("", "k")
        with pytest.raises(ValueError):
            s3_uri("b", "")


class TestInMemoryObjectStore:
    def test_matches_protocol(self):
        # InMemoryObjectStore must satisfy the ObjectStore structural protocol.
        assert isinstance(InMemoryObjectStore(), ObjectStore)

    def test_put_and_get_bytes(self):
        store = InMemoryObjectStore()
        uri = store.put_bytes(b"hello", "x/y.txt", content_type="text/plain")
        assert uri.startswith("s3://")
        assert store.get_bytes(uri) == b"hello"

    def test_put_file_round_trip(self, tmp_path: Path):
        p = tmp_path / "f.bin"
        p.write_bytes(b"\x00\x01\x02")
        store = InMemoryObjectStore()
        uri = store.put_file(p, "k")
        assert store.get_bytes(uri) == b"\x00\x01\x02"

    def test_exists(self):
        store = InMemoryObjectStore()
        uri = store.put_bytes(b"x", "k", content_type="application/octet-stream")
        assert store.exists(uri) is True
        assert store.exists("s3://inmem/nope") is False
        assert store.exists("not-a-uri") is False

    def test_get_missing_raises(self):
        store = InMemoryObjectStore()
        with pytest.raises(KeyError):
            store.get_bytes("s3://inmem/missing")

    def test_wrong_bucket_rejected(self):
        store = InMemoryObjectStore(bucket="a")
        store.put_bytes(b"x", "k", content_type="text/plain")
        with pytest.raises(ValueError):
            store.get_bytes("s3://b/k")

    def test_presigned_url_is_non_empty(self):
        # In-memory fake returns a pseudo-URL so callers can see which URI
        # was signed; exact format is unspecified beyond non-empty string.
        store = InMemoryObjectStore()
        uri = store.put_bytes(b"x", "k", content_type="text/plain")
        url = store.presigned_url(uri)
        assert isinstance(url, str)
        assert url
