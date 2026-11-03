"""M3.1: object storage against moto's in-memory S3."""

import pytest
from moto import mock_aws

from khataiq.config import get_settings
from khataiq.storage import get_store, upload_key


@pytest.fixture()
def store(monkeypatch):
    monkeypatch.setenv("KHATAIQ_S3_ENDPOINT", "")
    get_settings.cache_clear()
    get_store.cache_clear()
    with mock_aws():
        yield get_store()
    get_settings.cache_clear()
    get_store.cache_clear()


def test_key_layout():
    assert upload_key(3, 42, "ab" * 32) == f"org/3/upload/42/{'ab' * 32}"


def test_bucket_is_created_and_objects_round_trip(store):
    store.put_object("org/1/upload/1/x", b"hello", "text/csv")
    assert store.get_object("org/1/upload/1/x") == b"hello"
    assert store.exists("org/1/upload/1/x")
    assert not store.exists("org/1/upload/1/missing")


def test_ensure_bucket_is_idempotent(store):
    store.ensure_bucket()
    store.ensure_bucket()
