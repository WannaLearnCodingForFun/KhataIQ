"""Object storage for raw statement files (MinIO in development, any S3 API in production).

Keys look like org/{org_id}/upload/{upload_id}/{sha256}, so a file's location says which tenant
and upload it belongs to, and its content hash.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from khataiq.config import get_settings


def upload_key(org_id: int, upload_id: int, sha256: str) -> str:
    return f"org/{org_id}/upload/{upload_id}/{sha256}"


class Store(Protocol):
    def put_object(self, key: str, data: bytes, content_type: str) -> None: ...
    def get_object(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...


class LocalObjectStore:
    """Files under a directory, same key layout. For tests and offline development only."""

    def __init__(self, root: str) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError(f"key escapes the storage root: {key!r}")
        return path

    def put_object(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get_object(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()


class ObjectStore:
    def __init__(self, client: Any, bucket: str) -> None:
        self.client = client
        self.bucket = bucket

    def ensure_bucket(self) -> None:
        """Create the bucket if it's missing. Only for dev and tests; production buckets are
        provisioned with their own lifecycle and encryption policies."""
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)

    def put_object(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def get_object(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        body: bytes = response["Body"].read()
        return body

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError:
            return False
        return True


@lru_cache
def get_store() -> Store:
    settings = get_settings()
    if settings.storage_backend == "local":
        return LocalObjectStore(settings.local_storage_dir)
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint or None,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"},
                      s3={"addressing_style": "path"}),  # MinIO needs path-style URLs
    )
    store = ObjectStore(client, settings.s3_bucket)
    if settings.s3_create_bucket:
        store.ensure_bucket()
    return store
