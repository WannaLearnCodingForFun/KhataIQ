"""Shared pytest configuration: everything under tests/integration is marked `integration`."""

from pathlib import Path

import pytest

INTEGRATION_DIR = Path(__file__).parent / "integration"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if INTEGRATION_DIR in Path(str(item.fspath)).parents:
            item.add_marker(pytest.mark.integration)
