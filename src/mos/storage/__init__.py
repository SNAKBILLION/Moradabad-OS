"""Object storage: protocol + S3-compatible (MinIO/AWS) + in-memory test fake.

The system stores and reads s3://bucket/key URIs. The store implementations
handle transport; the URI format is the wire contract.
"""

from .memory import InMemoryObjectStore
from .store import ObjectStore, S3ObjectStore, parse_s3_uri, s3_uri

__all__ = [
    "InMemoryObjectStore",
    "ObjectStore",
    "S3ObjectStore",
    "parse_s3_uri",
    "s3_uri",
]
