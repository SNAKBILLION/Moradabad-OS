"""In-memory ObjectStore for unit tests.

Implements the same Protocol as S3ObjectStore but without boto3 or network.
Tests that exercise the orchestrator end-to-end use this so they don't need
MinIO up. The integration test in tests/integration/test_api_pipeline.py
uses the real S3ObjectStore and skips when MinIO isn't reachable.
"""

from __future__ import annotations

from pathlib import Path

from .store import parse_s3_uri, s3_uri


class InMemoryObjectStore:
    def __init__(self, bucket: str = "inmem") -> None:
        self._bucket = bucket
        self._data: dict[str, bytes] = {}

    @property
    def bucket(self) -> str:
        return self._bucket

    def put_file(self, local_path: Path, key: str) -> str:
        self._data[key] = local_path.read_bytes()
        return s3_uri(self._bucket, key)

    def put_bytes(self, data: bytes, key: str, content_type: str) -> str:
        # content_type accepted but ignored — no MIME metadata in memory.
        del content_type
        self._data[key] = data
        return s3_uri(self._bucket, key)

    def get_bytes(self, uri: str) -> bytes:
        bucket, key = parse_s3_uri(uri)
        if bucket != self._bucket:
            raise ValueError(f"wrong bucket: {bucket}")
        if key not in self._data:
            raise KeyError(key)
        return self._data[key]

    def presigned_url(self, uri: str, *, expires_seconds: int = 3600) -> str:
        del expires_seconds
        return f"memory://{uri}"

    def exists(self, uri: str) -> bool:
        try:
            bucket, key = parse_s3_uri(uri)
        except ValueError:
            return False
        return bucket == self._bucket and key in self._data
