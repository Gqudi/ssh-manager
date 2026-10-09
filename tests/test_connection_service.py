"""Duplicate handling, import conflict policies and launching."""

from __future__ import annotations

import pytest

from ssh_manager.database.models import Connection
from ssh_manager.services.connection_service import ConnectionService
from ssh_manager.services.ssh_config import ImportedHost
from ssh_manager.services.terminal import LaunchedTerminal


def create(service: ConnectionService, name: str, **overrides) -> Connection:
    data = {
        "name": name,
        "hostname": f"{name.lower()}.example.com",
        "username": "user",
    }
    data.update(overrides)
    return service.create(**data)


def imported(name: str, hostname: str = "imported.example.com") -> ImportedHost:
    return ImportedHost(name=name, hostname=hostname, username="user")


# ------------------------------------------------------------------ duplicates


def test_duplicates_get_unique_names(service: ConnectionService) -> None:
    original = create(service, "Prod")

    first = service.duplicate(original.id)
    second = service.duplicate(original.id)

    assert first is not None and second is not None
    assert first.name == "Prod (Copy)"
    assert second.name == "Prod (Copy) (2)"


def test_duplicate_copies_the_settings_but_not_the_identity(service: ConnectionService) -> None:
    original = create(service, "Prod", port=2222, proxy_jump="jump", notes="note")

    copy = service.duplicate(original.id)

    assert copy is not None
    assert copy.id != original.id
    assert copy.port == 2222
    assert copy.proxy_jump == "jump"
    assert copy.notes == "note"


def test_duplicate_of_a_missing_connection_is_none(service: ConnectionService) -> None:
    assert service.duplicate("does-not-exist") is None


# ------------------------------------------------------------------ import policies


def test_import_skips_clashing_names(service: ConnectionService) -> None:
    create(service, "Prod", hostname="old.example.com")

    summary = service.import_connections([imported("Prod")], "skip")

    assert (summary.imported, summary.skipped) == (0, 1)
    assert service.list_connections()[0].hostname == "old.example.com"


def test_import_overwrites_clashing_names_but_keeps_local_fields(
    service: ConnectionService,
) -> None:
    create(service, "Prod", hostname="old.example.com", notes="keep me", group_name="grp")

    summary = service.import_connections([imported("Prod")], "overwrite")

    assert (summary.overwritten, summary.imported) == (1, 0)
    stored = service.list_connections()[0]
    assert stored.hostname == "imported.example.com"
    assert (stored.notes, stored.group_name) == ("keep me", "grp")


def test_import_duplicates_clashing_names(service: ConnectionService) -> None:
    create(service, "Prod")

    summary = service.import_connections([imported("Prod")], "duplicate")

    assert summary.imported == 1
    assert {connection.name for connection in service.list_connections()} == {
        "Prod",
        "Prod (2)",
    }


def test_import_rejects_unknown_policies(service: ConnectionService) -> None:
    with pytest.raises(ValueError, match="Unknown conflict policy"):
        service.import_connections([imported("Prod")], "surprise")


# ------------------------------------------------------------------ launching


def test_connect_passes_the_built_arguments_to_the_terminal(
    monkeypatch, service: ConnectionService
) -> None:
    connection = create(service, "Prod", port=2222)
    calls: list[tuple[list[str], str]] = []

    def fake_open_terminal(ssh_args, terminal):
        calls.append((list(ssh_args), terminal))
        return LaunchedTerminal(name="kitty")

    monkeypatch.setattr(
        "ssh_manager.services.connection_service.open_terminal", fake_open_terminal
    )

    launched = service.connect(connection)

    assert launched.name == "kitty"
    args, terminal = calls[0]
    assert args[0] == "ssh"
    assert "-p" in args and "2222" in args
    assert "user@prod.example.com" in args
    assert terminal == connection.terminal
