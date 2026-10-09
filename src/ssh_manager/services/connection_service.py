from __future__ import annotations

import os
from collections.abc import Collection, Iterable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from ..database.database import Database
from ..database.models import Connection
from .ssh_config import ImportedHost, ImportSummary, serialize_connections
from .terminal import LaunchedTerminal, open_terminal


class ConnectionService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_connections(self, search: str = "") -> list[Connection]:
        with self.database.session() as session:
            stmt = select(Connection).order_by(Connection.name.asc())
            if search:
                pattern = f"%{search}%"
                stmt = stmt.where(
                    Connection.name.ilike(pattern)
                    | Connection.hostname.ilike(pattern)
                    | Connection.username.ilike(pattern)
                    | Connection.group_name.ilike(pattern)
                    | Connection.notes.ilike(pattern)
                    | Connection.private_key.ilike(pattern)
                )
            return list(session.scalars(stmt).all())

    def get(self, connection_id: str) -> Connection | None:
        with self.database.session() as session:
            return session.get(Connection, connection_id)

    def create(self, **data: Any) -> Connection:
        """Store a new connection; ``data`` are :class:`Connection` fields."""
        with self.database.session() as session:
            connection = Connection(id=str(uuid4()), **data)
            session.add(connection)
            session.commit()
            session.refresh(connection)
            return connection

    def update(self, connection_id: str, **data: Any) -> Connection | None:
        with self.database.session() as session:
            connection = session.get(Connection, connection_id)
            if connection is None:
                return None
            for key, value in data.items():
                setattr(connection, key, value)
            connection.updated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(connection)
            return connection

    def delete(self, connection_id: str) -> bool:
        with self.database.session() as session:
            connection = session.get(Connection, connection_id)
            if connection is None:
                return False
            session.delete(connection)
            session.commit()
            return True

    def duplicate(self, connection_id: str) -> Connection | None:
        original = self.get(connection_id)
        if original is None:
            return None
        return self.create(
            name=self._unique_name(f"{original.name} (Copy)", self.existing_names()),
            hostname=original.hostname,
            port=original.port,
            username=original.username,
            auth_method=original.auth_method,
            private_key=original.private_key,
            group_name=original.group_name,
            notes=original.notes,
            forward_agent=original.forward_agent,
            compression=original.compression,
            x11_forwarding=original.x11_forwarding,
            server_alive_interval=original.server_alive_interval,
            proxy_jump=original.proxy_jump,
            remote_command=original.remote_command,
            extra_options=original.extra_options,
            terminal=original.terminal,
        )

    # ------------------------------------------------------------------ import/export

    def existing_names(self) -> set[str]:
        """Lower-cased names already stored, for import conflict previews."""
        with self.database.session() as session:
            return {name.lower() for name in session.scalars(select(Connection.name)).all()}

    def import_connections(
        self,
        hosts: Iterable[ImportedHost],
        conflict_policy: str = "skip",
    ) -> ImportSummary:
        """Store imported hosts; ``conflict_policy`` is skip/overwrite/duplicate."""
        if conflict_policy not in {"skip", "overwrite", "duplicate"}:
            raise ValueError(f"Unknown conflict policy: {conflict_policy}")

        summary = ImportSummary()
        with self.database.session() as session:
            by_name = {
                connection.name.lower(): connection
                for connection in session.scalars(select(Connection)).all()
            }

            for host in hosts:
                summary.warnings.extend(host.warnings)
                current = by_name.get(host.name.lower())

                if current is not None:
                    if conflict_policy == "skip":
                        summary.skipped += 1
                        continue
                    if conflict_policy == "overwrite":
                        data = host.to_connection_kwargs()
                        for field_name in ("name", "group_name", "notes", "terminal"):
                            data.pop(field_name, None)
                        for field_name, value in data.items():
                            setattr(current, field_name, value)
                        current.updated_at = datetime.now(timezone.utc)
                        summary.overwritten += 1
                        continue
                    data = host.to_connection_kwargs()
                    data["name"] = self._unique_name(host.name, by_name)
                    connection = Connection(id=str(uuid4()), **data)
                    session.add(connection)
                    by_name[connection.name.lower()] = connection
                    summary.imported += 1
                    continue

                connection = Connection(id=str(uuid4()), **host.to_connection_kwargs())
                session.add(connection)
                by_name[connection.name.lower()] = connection
                summary.imported += 1

            session.commit()
        return summary

    @staticmethod
    def _unique_name(base: str, existing: Collection[str]) -> str:
        """``base`` if it is still free, otherwise ``base (2)``, ``base (3)``, …

        ``existing`` holds lower-cased names, as returned by
        :meth:`existing_names`.
        """
        if base.lower() not in existing:
            return base
        index = 2
        while f"{base} ({index})".lower() in existing:
            index += 1
        return f"{base} ({index})"

    def export_ssh_config(self) -> str:
        return serialize_connections(self.list_connections())

    # ------------------------------------------------------------------ connecting

    @staticmethod
    def _extra_option_keyword(line: str) -> str:
        for index, char in enumerate(line):
            if char in "= \t":
                return line[:index].lower()
        return line.lower()

    @staticmethod
    def build_ssh_args(connection: Connection) -> list[str]:
        args = ["ssh", "-p", str(connection.port or 22)]

        extra_lines = [
            line.strip()
            for line in (connection.extra_options or "").splitlines()
            if line.strip()
        ]
        # OpenSSH keeps the first value for a repeated -o keyword, so do not emit
        # a default when the user's extra options already set the same keyword.
        extra_keywords = {
            ConnectionService._extra_option_keyword(line) for line in extra_lines
        }

        def add_option(option: str) -> None:
            """Append ``-o option`` unless the user overrode that keyword."""
            if ConnectionService._extra_option_keyword(option) not in extra_keywords:
                args.extend(["-o", option])

        # The authentication method decides which methods ssh may try; without
        # these flags every method would just be left at OpenSSH's defaults.
        auth_method = connection.auth_method or "agent"
        if auth_method == "key" and connection.private_key:
            args += ["-i", os.path.expanduser(connection.private_key)]
            # Offer exactly this key, so the agent's other identities cannot
            # exhaust the server's authentication attempts.
            add_option("IdentitiesOnly=yes")
        elif auth_method == "password":
            add_option("PreferredAuthentications=password,keyboard-interactive")
            add_option("PubkeyAuthentication=no")

        if connection.forward_agent:
            args.append("-A")
        if connection.compression:
            args.append("-C")
        if connection.x11_forwarding:
            args.append("-X")

        if (
            connection.server_alive_interval or 0
        ) > 0 and "serveraliveinterval" not in extra_keywords:
            args += ["-o", f"ServerAliveInterval={connection.server_alive_interval}"]
            add_option("ServerAliveCountMax=3")
        if connection.proxy_jump:
            args += ["-J", connection.proxy_jump.strip()]

        # Extra options are entered one option per line, e.g.:
        # StrictHostKeyChecking=no
        # SendEnv=LANG
        for line in extra_lines:
            args += ["-o", line]

        if connection.remote_command and "requesttty" not in extra_keywords:
            # ssh allocates a pseudo-terminal by itself only when no command is
            # given.  With one it does not, so the remote program runs without
            # a TERM and screen programs (htop, top, tmux, …) fail to start.
            # -t asks for the pty an interactive login would get.
            args.append("-t")

        args.append(f"{connection.username}@{connection.hostname}")

        if connection.remote_command:
            args.append(connection.remote_command)

        return args

    def connect(self, connection: Connection) -> LaunchedTerminal:
        """Open the connection in a new terminal window."""
        return open_terminal(self.build_ssh_args(connection), connection.terminal)
