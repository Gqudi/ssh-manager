import os

from ssh_manager.database.models import Connection
from ssh_manager.services.connection_service import ConnectionService


def build_args(**overrides) -> list[str]:
    data = {
        "name": "Prod",
        "hostname": "example.com",
        "username": "user",
        "port": 2222,
        "auth_method": "key",
        "private_key": "~/.ssh/id_ed25519",
        "forward_agent": True,
        "compression": True,
        "server_alive_interval": 30,
        "proxy_jump": "jump.example.com",
        "remote_command": "htop",
        "extra_options": "StrictHostKeyChecking=accept-new\nSendEnv=LANG",
    }
    data.update(overrides)
    return ConnectionService.build_ssh_args(Connection(**data))


def test_build_ssh_args():
    args = build_args()

    assert args[:5] == [
        "ssh",
        "-p",
        "2222",
        "-i",
        os.path.expanduser("~/.ssh/id_ed25519"),
    ]
    assert "-A" in args
    assert "-C" in args
    assert "-J" in args
    assert "jump.example.com" in args
    assert "user@example.com" in args
    assert "htop" in args
    assert "StrictHostKeyChecking=accept-new" in args
    assert "SendEnv=LANG" in args


def test_key_authentication_offers_only_the_configured_key():
    args = build_args(extra_options=None)

    assert "-i" in args
    assert "IdentitiesOnly=yes" in args


def test_agent_authentication_ignores_a_stale_key_path():
    args = build_args(auth_method="agent", extra_options=None)

    assert "-i" not in args
    assert "IdentitiesOnly=yes" not in args


def test_password_authentication_turns_public_key_off():
    args = build_args(auth_method="password", private_key=None, extra_options=None)

    assert "PreferredAuthentications=password,keyboard-interactive" in args
    assert "PubkeyAuthentication=no" in args
    assert "-i" not in args


def test_extra_options_override_the_authentication_defaults():
    key_args = build_args(extra_options="IdentitiesOnly=no")
    assert "IdentitiesOnly=yes" not in key_args
    assert "IdentitiesOnly=no" in key_args

    password_args = build_args(
        auth_method="password", private_key=None, extra_options="PubkeyAuthentication=yes"
    )
    assert "PubkeyAuthentication=no" not in password_args
    assert "PubkeyAuthentication=yes" in password_args


def test_extra_options_can_override_server_alive_count_max():
    args = build_args(extra_options="ServerAliveCountMax=9")

    assert "ServerAliveInterval=30" in args
    assert "ServerAliveCountMax=3" not in args
    assert "ServerAliveCountMax=9" in args


def test_extra_options_can_override_the_server_alive_interval():
    args = build_args(server_alive_interval=30, extra_options="ServerAliveInterval=60")

    assert "ServerAliveInterval=30" not in args
    assert "ServerAliveInterval=60" in args


def test_remote_command_requests_a_pseudo_terminal():
    # Without -t, ssh sends no pty and the remote program gets no TERM, so
    # things like htop cannot even initialise ncurses.
    args = build_args(remote_command="htop", extra_options=None)

    assert "-t" in args
    assert args.index("-t") < args.index("user@example.com")
    assert args[-1] == "htop"


def test_remote_command_respects_an_explicit_request_tty_option():
    args = build_args(
        remote_command="uptime", extra_options="RequestTTY=no", auth_method="agent"
    )

    assert "-t" not in args
    assert "RequestTTY=no" in args


def test_plain_login_does_not_force_a_pseudo_terminal():
    # ssh allocates the pty itself when no command is given.
    args = build_args(remote_command=None, extra_options=None)

    assert "-t" not in args
