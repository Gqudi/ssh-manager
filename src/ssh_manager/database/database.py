from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStandardPaths
from sqlalchemy import create_engine

from .models import Base


class Database:
    def __init__(self) -> None:
        app_data = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppLocalDataLocation
        )
        self.directory = Path(app_data)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "ssh-manager.sqlite3"

        self.engine = create_engine(
            f"sqlite:///{self.path}",
            future=True,
            connect_args={"check_same_thread": False},
        )

    def create_tables(self) -> None:
        Base.metadata.create_all(self.engine)

    def session(self):
        from sqlalchemy.orm import sessionmaker
        return sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
        )()
