from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Connection(Base):
    __tablename__ = "connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=22)
    username: Mapped[str] = mapped_column(String(128), nullable=False)
    auth_method: Mapped[str] = mapped_column(String(32), nullable=False, default="agent")
    private_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    group_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    forward_agent: Mapped[bool] = mapped_column(nullable=False, default=False)
    compression: Mapped[bool] = mapped_column(nullable=False, default=False)
    x11_forwarding: Mapped[bool] = mapped_column(nullable=False, default=False)
    server_alive_interval: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    proxy_jump: Mapped[str | None] = mapped_column(String(255), nullable=True)
    remote_command: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_options: Mapped[str | None] = mapped_column(Text, nullable=True)
    terminal: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
