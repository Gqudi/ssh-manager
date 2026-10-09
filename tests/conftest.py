"""Shared fixtures.

UI tests run headless, and the settings object is always injected, so a test
run never reads or writes the user's real configuration.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ssh_manager.database.database import Database
from ssh_manager.services.connection_service import ConnectionService


def pytest_configure(config: pytest.Config) -> None:
    del config
    # Selected before any test imports Qt: the offscreen plugin needs no display.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def database(tmp_path: Path) -> Database:
    database = Database(tmp_path)
    database.initialize()
    return database


@pytest.fixture
def service(database: Database) -> ConnectionService:
    return ConnectionService(database)


@pytest.fixture(scope="session")
def qapp():
    """A QApplication, which every widget test needs."""
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])
