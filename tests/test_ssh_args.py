import os

from ssh_manager.database.models import Connection
from ssh_manager.services.connection_service import ConnectionService


def test_build_ssh_args():
    c = Connection(
        name="Prod",
        hostname="example.com",
        username="user",
        port=2222,
        private_key="~/.ssh/id_ed25519",
        forward_agent=True,
        compression=True,
        server_alive_interval=30,
        proxy_jump="jump.example.com",
        remote_command="htop",
        extra_options="StrictHostKeyChecking=accept-new\nSendEnv=LANG",
    )
    args = ConnectionService.build_ssh_args(c)

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


def test_extra_options_can_override_server_alive_count_max():
    c = Connection(
        name="Prod",
        hostname="example.com",
        username="user",
        server_alive_interval=30,
        extra_options="ServerAliveCountMax=9",
    )
    args = ConnectionService.build_ssh_args(c)

    assert "ServerAliveInterval=30" in args
    assert "ServerAliveCountMax=3" not in args
    assert "ServerAliveCountMax=9" in args
