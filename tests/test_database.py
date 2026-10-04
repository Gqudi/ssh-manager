from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

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
