"""SQLite storage with a lightweight, ordered schema-migration path.

``create_all`` only ever creates *missing* tables, so on its own it cannot
evolve an existing database: adding a field to a model would leave older
databases without the new column.  :class:`Database` therefore keeps a schema
version in SQLite's ``user_version`` pragma and applies the statements listed
in :data:`MIGRATIONS` in order.

Databases created by v0.1 carry ``user_version = 0``; :meth:`Database.initialize`
recognises them as already matching the v1 schema and stamps them.  Before a
migration touches a database it is copied to ``<name>.v<old>.bak`` next to the
original, and a database written by a newer release is refused instead of being
silently downgraded.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, Connection


@dataclass(frozen=True)
class Migration:
    """One step between schema versions, applied as a single transaction."""

    version: int
    description: str
    statements: tuple[str, ...]


#: Ordered migrations for databases created by older releases.  Add one entry
#: per schema change and bump :attr:`Database.SCHEMA_VERSION` to match; the
#: chain is validated in :meth:`Database._validate_migration_chain`.
MIGRATIONS: tuple[Migration, ...] = ()


class SchemaTooNewError(RuntimeError):
    """The database was written by a newer version of the application."""


class Database:
    SCHEMA_VERSION = 1

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "ssh-manager.sqlite3"

        self.engine = create_engine(
            f"sqlite:///{self.path}",
            future=True,
            connect_args={"check_same_thread": False},
        )
        self._session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
        )

    def session(self) -> Session:
        return self._session_factory()

    # ------------------------------------------------------------------ schema

    def initialize(self) -> None:
        """Create the schema, or migrate an existing database forward."""
        self._validate_migration_chain()

        if not inspect(self.engine).has_table(Connection.__tablename__):
            Base.metadata.create_all(self.engine)
            self._set_schema_version(self.SCHEMA_VERSION)
            return

        stored = self.schema_version()
        # A v0.1 database predates the pragma but already matches schema v1,
        # so it only needs the migrations that came after it.
        version = stored or 1
        if version > self.SCHEMA_VERSION:
            raise SchemaTooNewError(
                f"The database at {self.path} uses schema version {stored}, but "
                f"this version of SSH Manager only understands version "
                f"{self.SCHEMA_VERSION}. Please update the application."
            )

        pending = [
            migration
            for migration in MIGRATIONS
            if version < migration.version <= self.SCHEMA_VERSION
        ]
        if pending:
            self._backup(version)
            with self.engine.begin() as connection:
                for migration in pending:
                    for statement in migration.statements:
                        connection.exec_driver_sql(statement)
        if stored != self.SCHEMA_VERSION:
            self._set_schema_version(self.SCHEMA_VERSION)

    def schema_version(self) -> int:
        """The schema version recorded in the database file (0 = pre-versioning)."""
        with self.engine.connect() as connection:
            return int(connection.exec_driver_sql("PRAGMA user_version").scalar() or 0)

    def _set_schema_version(self, version: int) -> None:
        with self.engine.begin() as connection:
            # PRAGMA does not accept bound parameters; the value is an int.
            connection.exec_driver_sql(f"PRAGMA user_version = {int(version)}")

    def _backup(self, version: int) -> Path:
        backup = self.path.with_name(f"{self.path.name}.v{version}.bak")
        shutil.copy2(self.path, backup)
        return backup

    @classmethod
    def _validate_migration_chain(cls) -> None:
        """Fail loudly if SCHEMA_VERSION and MIGRATIONS disagree."""
        expected = list(range(2, cls.SCHEMA_VERSION + 1))
        actual = [migration.version for migration in MIGRATIONS]
        if actual != expected:
            raise RuntimeError(
                f"MIGRATIONS {actual} does not cover SCHEMA_VERSION "
                f"{cls.SCHEMA_VERSION} (expected version numbers {expected})."
            )
