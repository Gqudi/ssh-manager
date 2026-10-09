from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from ssh_manager.database import database as database_module
from ssh_manager.database.database import Database, Migration, SchemaTooNewError
from ssh_manager.database.models import Base, Connection


def test_connection_model():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)

    with Session() as session:
        connection = Connection(
            name="Test",
            hostname="example.com",
            username="test",
        )
        session.add(connection)
        session.commit()

        assert connection.id
        assert connection.port == 22
        assert connection.name == "Test"


def test_initialize_creates_and_stamps_the_schema(tmp_path: Path) -> None:
    database = Database(tmp_path)
    database.initialize()

    assert database.path.exists()
    assert inspect(database.engine).has_table("connections")
    assert database.schema_version() == Database.SCHEMA_VERSION


def test_initialize_is_idempotent(tmp_path: Path) -> None:
    database = Database(tmp_path)
    database.initialize()
    database.initialize()

    assert database.schema_version() == Database.SCHEMA_VERSION


def test_v0_1_database_is_adopted_without_data_loss(tmp_path: Path) -> None:
    # v0.1 created its tables from these very models, but knew no pragma.
    database = Database(tmp_path)
    Base.metadata.create_all(database.engine)
    with database.session() as session:
        session.add(Connection(name="Prod", hostname="example.com", username="user"))
        session.commit()

    assert database.schema_version() == 0
    database.initialize()

    assert database.schema_version() == Database.SCHEMA_VERSION
    with database.session() as session:
        assert session.scalars(select(Connection)).one().name == "Prod"


ADD_FAVOURITE = Migration(
    version=2,
    description="remember favourited connections",
    statements=(
        "ALTER TABLE connections ADD COLUMN favourite BOOLEAN NOT NULL DEFAULT 0",
    ),
)


def test_pending_migration_is_applied_and_backed_up(tmp_path, monkeypatch) -> None:
    database = Database(tmp_path)
    database.initialize()
    with database.session() as session:
        session.add(Connection(name="Prod", hostname="example.com", username="user"))
        session.commit()

    monkeypatch.setattr(Database, "SCHEMA_VERSION", 2)
    monkeypatch.setattr(database_module, "MIGRATIONS", (ADD_FAVOURITE,))
    database.initialize()

    assert database.schema_version() == 2
    columns = {column["name"] for column in inspect(database.engine).get_columns("connections")}
    assert "favourite" in columns
    assert (tmp_path / f"{database.path.name}.v1.bak").exists()
    with database.session() as session:
        assert session.scalars(select(Connection)).one().name == "Prod"


def test_failed_migration_does_not_stamp_the_new_version(tmp_path, monkeypatch) -> None:
    database = Database(tmp_path)
    database.initialize()

    broken = Migration(
        version=2,
        description="broken",
        statements=("ALTER TABLE does_not_exist ADD COLUMN x INTEGER",),
    )
    monkeypatch.setattr(Database, "SCHEMA_VERSION", 2)
    monkeypatch.setattr(database_module, "MIGRATIONS", (broken,))

    with pytest.raises(OperationalError):
        database.initialize()

    assert database.schema_version() == 1


def test_database_from_a_newer_release_is_refused(tmp_path: Path) -> None:
    database = Database(tmp_path)
    database.initialize()
    with database.engine.begin() as connection:
        connection.execute(text("PRAGMA user_version = 99"))

    with pytest.raises(SchemaTooNewError, match="99"):
        database.initialize()


def test_migration_chain_must_cover_the_schema_version(tmp_path, monkeypatch) -> None:
    database = Database(tmp_path)
    database.initialize()

    # A version bump without the matching migration must not pass silently.
    monkeypatch.setattr(Database, "SCHEMA_VERSION", 3)
    monkeypatch.setattr(database_module, "MIGRATIONS", (ADD_FAVOURITE,))

    with pytest.raises(RuntimeError, match="MIGRATIONS"):
        database.initialize()
