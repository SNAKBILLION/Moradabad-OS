"""Object storage.

Phase 1 uses MinIO locally and S3 in production. Both speak the same S3
protocol so boto3 covers both; the difference is endpoint URL and creds.

URIs are stored in the DB as ``s3://{bucket}/{key}``. The translation to
signed HTTP URLs happens only at the API boundary via ``presigned_url``.
The rest of the system deals in ``s3://...`` to stay transport-agnostic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError


# --- Public URI helpers --------------------------------------------------

def s3_uri(bucket: str, key: str) -> str:
    if not bucket or not key:
        raise ValueError("bucket and key must both be non-empty")
    return f"s3://{bucket}/{key}"


def parse_s3_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"not an s3 URI: {uri!r}")
    without_scheme = uri[len("s3://"):]
    if "/" not in without_scheme:
        raise ValueError(f"s3 URI missing key: {uri!r}")
    bucket, key = without_scheme.split("/", 1)
    if not bucket or not key:
        raise ValueError(f"s3 URI has empty bucket or key: {uri!r}")
    return bucket, key


# --- Protocol ------------------------------------------------------------

@runtime_checkable
class ObjectStore(Protocol):
    def put_file(self, local_path: Path, key: str) -> str: ...
    def put_bytes(self, data: bytes, key: str, content_type: str) -> str: ...
    def get_bytes(self, uri: str) -> bytes: ...
    def presigned_url(self, uri: str, *, expires_seconds: int = 3600) -> str: ...
    def exists(self, uri: str) -> bool: ...


# --- S3-compatible implementation ----------------------------------------

class S3ObjectStore:
    """Works with both MinIO and AWS S3. Constructor takes explicit config so
    tests can point at a local MinIO without mutating environment."""

    def __init__(
        self,
        *,
        endpoint: str | None,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str = "us-east-1",
    ) -> None:
        self._bucket = bucket
        # Using path-style addressing — MinIO defaults to this, AWS accepts it.
        # Avoids vhost-style DNS requirements in local dev.
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=BotoConfig(s3={"addressing_style": "path"}),
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError as e:
            # 404 = bucket doesn't exist; create it. Other errors bubble up.
            code = e.response.get("Error", {}).get("Code")
            if code in ("404", "NoSuchBucket", "NotFound"):
                self._client.create_bucket(Bucket=self._bucket)
            else:
                raise

    @property
    def bucket(self) -> str:
        return self._bucket

    def put_file(self, local_path: Path, key: str) -> str:
        if not local_path.is_file():
            raise FileNotFoundError(local_path)
        self._client.upload_file(str(local_path), self._bucket, key)
        return s3_uri(self._bucket, key)

    def put_bytes(self, data: bytes, key: str, content_type: str) -> str:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return s3_uri(self._bucket, key)

    def get_bytes(self, uri: str) -> bytes:
        bucket, key = parse_s3_uri(uri)
        if bucket != self._bucket:
            raise ValueError(
                f"uri bucket {bucket!r} does not match this store "
                f"({self._bucket!r})"
            )
        resp = self._client.get_object(Bucket=bucket, Key=key)
        return resp["Body"].read()

    def presigned_url(
        self, uri: str, *, expires_seconds: int = 3600
    ) -> str:
        bucket, key = parse_s3_uri(uri)
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )

    def exists(self, uri: str) -> bool:
        bucket, key = parse_s3_uri(uri)
        try:
            self._client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code in ("404", "NoSuchKey", "NotFound"):
                return False
            raise
