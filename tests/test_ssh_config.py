import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ssh_manager.database.models import Base, Connection
from ssh_manager.services.connection_service import ConnectionService
from ssh_manager.services.ssh_config import (
    ImportedHost,
    parse_ssh_config,
    parse_ssh_config_report,
    serialize_connections,
)

SAMPLE = """\
# personal servers
Host prod
    HostName prod.example.com
    User deploy
    Port 2222
    IdentityFile ~/.ssh/id_ed25519
    ProxyJump bastion
    ForwardAgent yes
    Compression yes
    ForwardX11 no
    ServerAliveInterval 30
    RemoteCommand htop
    StrictHostKeyChecking=accept-new
    SetEnv TERM=xterm-256color

Host db staging
    HostName db.example.com

Host *.internal
    User admin

Match host *.example.com
    User ignored

Include ~/.ssh/config.d/*
"""


class StubDatabase:
    """In-memory stand-in for Database (mirrors tests/test_database.py)."""

    def __init__(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self._sessionmaker = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )

    def session(self):
        return self._sessionmaker()


def make_connection(**overrides) -> Connection:
    data = {"name": "prod", "hostname": "prod.example.com", "username": "deploy"}
    data.update(overrides)
    return Connection(**data)


def make_service() -> ConnectionService:
    return ConnectionService(StubDatabase())


# ------------------------------------------------------------------ parsing


def test_parse_maps_directives():
    report = parse_ssh_config_report(SAMPLE, username="fallback")
    assert [host.name for host in report.hosts] == ["prod", "db", "staging"]

    prod = report.hosts[0]
    assert prod.hostname == "prod.example.com"
    assert prod.username == "deploy"
    assert prod.port == 2222
    assert prod.private_key == os.path.expanduser("~/.ssh/id_ed25519")
    assert prod.auth_method == "key"
    assert prod.proxy_jump == "bastion"
    assert prod.forward_agent is True
    assert prod.compression is True
    assert prod.x11_forwarding is False
    assert prod.server_alive_interval == 30
    assert prod.remote_command == "htop"
    assert prod.extra_options == [
        "StrictHostKeyChecking=accept-new",
        "SetEnv=TERM=xterm-256color",
    ]


def test_parse_multi_pattern_host_shares_options():
    hosts = parse_ssh_config(SAMPLE, username="fallback")
    db = next(host for host in hosts if host.name == "db")
    staging = next(host for host in hosts if host.name == "staging")
    assert db.hostname == staging.hostname == "db.example.com"
    assert db.username == staging.username == "fallback"
    assert db.port == staging.port == 22
    assert db.auth_method == staging.auth_method == "agent"


def test_parse_skips_wildcards_match_and_include():
    report = parse_ssh_config_report(SAMPLE)
    warnings = " ".join(report.warnings)
    assert "*.internal" in warnings
    assert "Match" in warnings
    assert "Include" in warnings


def test_parse_global_options_apply_to_all_hosts():
    hosts = parse_ssh_config("User admin\nServerAliveInterval 15\n\nHost one\nHost two\n")
    assert [host.name for host in hosts] == ["one", "two"]
    assert all(host.username == "admin" for host in hosts)
    assert all(host.server_alive_interval == 15 for host in hosts)


def test_parse_quoted_value_and_equals_form():
    host = parse_ssh_config('Host q\n    HostName "my host.example.com"\n    Port=2200\n')[0]
    assert host.hostname == "my host.example.com"
    assert host.port == 2200


def test_parse_backslash_continuation():
    host = parse_ssh_config(
        "Host joined\n    HostName joined.example.com\n    User \\\n        bob\n"
    )[0]
    assert host.username == "bob"


def test_parse_inline_comment_is_part_of_value():
    host = parse_ssh_config("Host c\n    HostName host.example.com # note\n")[0]
    assert host.hostname == "host.example.com # note"


def test_parse_invalid_values_fall_back_with_warnings():
    report = parse_ssh_config_report("Host bad\n    Port nope\n    ForwardAgent maybe\n")
    host = report.hosts[0]
    assert host.port == 22
    assert host.forward_agent is False
    assert any("Port" in warning for warning in host.warnings)
    assert any("ForwardAgent" in warning for warning in host.warnings)


def test_parse_identity_file_none_and_repeats():
    hosts = parse_ssh_config(
        "Host a\n    IdentityFile none\n\n"
        "Host b\n    IdentityFile /tmp/k1\n    IdentityFile /tmp/k2\n"
    )
    assert hosts[0].private_key is None
    assert hosts[0].auth_method == "agent"
    assert hosts[1].private_key == "/tmp/k1"
    assert any("only the first IdentityFile" in warning for warning in hosts[1].warnings)


def test_parse_none_values():
    host = parse_ssh_config("Host a\n    ProxyJump none\n    RemoteCommand none\n")[0]
    assert host.proxy_jump is None
    assert host.remote_command is None


def test_parse_duplicate_alias_first_wins():
    report = parse_ssh_config_report("Host dup\n    User first\n\nHost dup\n    User second\n")
    assert len(report.hosts) == 1
    assert report.hosts[0].username == "first"
    assert any("Duplicate" in warning for warning in report.warnings)


def test_parse_empty_and_comment_only():
    assert parse_ssh_config("") == []
    assert parse_ssh_config("# just a comment\n\n") == []


def test_to_connection_kwargs():
    host = ImportedHost(
        name="a", hostname="h", username="u", extra_options=["A=1", "B=2"]
    )
    kwargs = host.to_connection_kwargs()
    assert kwargs["group_name"] is None
    assert kwargs["terminal"] == "system"
    assert kwargs["extra_options"] == "A=1\nB=2"


# ------------------------------------------------------------------ serialization


def test_serialize_emits_non_defaults_only():
    text = serialize_connections([make_connection()])
    assert "Host prod" in text
    assert "    HostName prod.example.com" in text
    assert "    User deploy" in text
    assert "Port" not in text
    assert "ForwardAgent" not in text


def test_serialize_full_block():
    connection = make_connection(
        port=2222,
        auth_method="key",
        private_key="~/.ssh/id_ed25519",
        proxy_jump="bastion",
        forward_agent=True,
        compression=True,
        x11_forwarding=True,
        server_alive_interval=30,
        remote_command="htop",
        extra_options="StrictHostKeyChecking=accept-new\nSetEnv=LANG",
    )
    text = serialize_connections([connection])
    for expected in (
        "    Port 2222",
        "    IdentityFile ~/.ssh/id_ed25519",
        "    ProxyJump bastion",
        "    ForwardAgent yes",
        "    Compression yes",
        "    ForwardX11 yes",
        "    ServerAliveInterval 30",
        "    RemoteCommand htop",
        "    StrictHostKeyChecking=accept-new",
        "    SetEnv=LANG",
    ):
        assert expected in text


def test_serialize_sanitizes_and_uniquifies_aliases():
    text = serialize_connections(
        [
            make_connection(name="prod host"),
            make_connection(name="prod*host"),
            make_connection(name="*"),
        ]
    )
    assert "Host prod-host\n" in text
    assert "Host prod-host-2\n" in text
    assert "Host host\n" in text


def test_serialize_round_trip():
    connection = make_connection(
        port=2222,
        auth_method="key",
        private_key="/tmp/key",
        proxy_jump="bastion",
        forward_agent=True,
        server_alive_interval=60,
        extra_options="SendEnv=LANG",
    )
    host = parse_ssh_config(serialize_connections([connection]))[0]
    assert host.name == "prod"
    assert host.hostname == "prod.example.com"
    assert host.username == "deploy"
    assert host.port == 2222
    assert host.private_key == "/tmp/key"
    assert host.proxy_jump == "bastion"
    assert host.forward_agent is True
    assert host.server_alive_interval == 60
    assert host.extra_options == ["SendEnv=LANG"]


# ------------------------------------------------------------------ service import/export


def test_import_creates_and_skips_conflicts():
    service = make_service()
    service.create(name="prod", hostname="old.example.com", username="old")

    summary = service.import_connections(
        [
            ImportedHost(name="prod", hostname="new.example.com", username="new"),
            ImportedHost(name="db", hostname="db.example.com", username="deploy"),
        ]
    )

    assert summary.imported == 1
    assert summary.skipped == 1
    connections = {connection.name: connection for connection in service.list_connections()}
    assert set(connections) == {"prod", "db"}
    assert connections["prod"].hostname == "old.example.com"


def test_import_overwrite_preserves_local_fields():
    service = make_service()
    service.create(
        name="prod", hostname="old", username="u", notes="keep me", terminal="kitty"
    )

    summary = service.import_connections(
        [ImportedHost(name="prod", hostname="new", username="u")],
        conflict_policy="overwrite",
    )

    assert summary.overwritten == 1
    prod = service.list_connections()[0]
    assert prod.hostname == "new"
    assert prod.notes == "keep me"
    assert prod.terminal == "kitty"


def test_import_duplicate_policy_uniquifies_names():
    service = make_service()
    service.create(name="prod", hostname="old", username="u")

    summary = service.import_connections(
        [ImportedHost(name="prod", hostname="new", username="u")],
        conflict_policy="duplicate",
    )

    assert summary.imported == 1
    assert {connection.name for connection in service.list_connections()} == {
        "prod",
        "prod (2)",
    }


def test_import_rejects_unknown_policy():
    service = make_service()
    with pytest.raises(ValueError):
        service.import_connections([], conflict_policy="explode")


def test_import_surfaces_host_warnings():
    service = make_service()
    summary = service.import_connections(
        [ImportedHost(name="a", hostname="h", username="u", warnings=("oops",))]
    )
    assert summary.warnings == ["oops"]


def test_export_round_trips_through_database():
    service = make_service()
    service.create(
        name="prod",
        hostname="prod.example.com",
        username="deploy",
        port=2222,
        extra_options="SetEnv=LANG",
    )

    host = parse_ssh_config(service.export_ssh_config())[0]

    assert host.name == "prod"
    assert host.port == 2222
    assert host.extra_options == ["SetEnv=LANG"]
