import subprocess
from pathlib import Path

import pytest

from ssh_manager.database.models import Connection
from ssh_manager.services.connection_service import ConnectionService
from ssh_manager.services.terminal import (
    TerminalLaunchError,
    TerminalNotFoundError,
    build_command,
    open_terminal,
    resolve_terminal,
)

SSH_ARGS = ["ssh", "-p", "2222", "user@example.com"]


def make_which(installed: set[str]):
    def which(name: str) -> str | None:
        base = Path(name).name
        if base in installed:
            return f"/usr/bin/{base}"
        return None

    return which


@pytest.fixture
def spawn(monkeypatch):
    """Record every argv handed to subprocess.Popen instead of launching it."""
    spawned: list[tuple[list[str], dict]] = []

    class FakePopen:
        def __init__(self, argv, **kwargs):
            spawned.append((list(argv), kwargs))

    monkeypatch.setattr("ssh_manager.services.terminal.subprocess.Popen", FakePopen)
    return spawned


@pytest.mark.parametrize(
    ("terminal", "expected"),
    [
        ("kitty", ["kitty", "--hold", *SSH_ARGS]),
        ("konsole", ["konsole", "--hold", "-e", *SSH_ARGS]),
        ("gnome-terminal", ["gnome-terminal", "--", *SSH_ARGS]),
        ("kgx", ["kgx", "--", *SSH_ARGS]),
        ("alacritty", ["alacritty", "-e", *SSH_ARGS]),
        ("foot", ["foot", *SSH_ARGS]),
        ("wezterm", ["wezterm", "start", "--", *SSH_ARGS]),
        ("xterm", ["xterm", "-e", *SSH_ARGS]),
    ],
)
def test_build_command_variants(terminal, expected):
    assert build_command(terminal, SSH_ARGS) == expected


def test_build_command_joined_argument_terminals():
    assert build_command("xfce4-terminal", SSH_ARGS) == [
        "xfce4-terminal",
        "--command",
        "ssh -p 2222 user@example.com",
    ]
    assert build_command("tilix", SSH_ARGS) == [
        "tilix",
        "-e",
        "ssh -p 2222 user@example.com",
    ]


def test_build_command_uses_basename_and_unknown_fallback():
    assert build_command("/opt/bin/kitty", SSH_ARGS)[:2] == ["/opt/bin/kitty", "--hold"]
    assert build_command("/opt/bin/mystery", SSH_ARGS) == [
        "/opt/bin/mystery",
        "-e",
        *SSH_ARGS,
    ]


def test_build_command_prefix_args():
    assert build_command("kitty", SSH_ARGS, ["--single-instance"]) == [
        "kitty",
        "--single-instance",
        "--hold",
        *SSH_ARGS,
    ]


def test_resolve_prefers_configured_terminal():
    resolved = resolve_terminal(
        "xterm",
        environ={},
        home=Path("/nonexistent"),
        which=make_which({"xterm", "kitty"}),
    )
    assert resolved.name == "xterm"
    assert resolved.executable == "/usr/bin/xterm"


def test_resolve_falls_back_when_configured_terminal_missing():
    resolved = resolve_terminal(
        "konsole",
        environ={},
        home=Path("/nonexistent"),
        which=make_which({"kitty"}),
    )
    assert resolved.name == "kitty"
    assert any("konsole" in warning for warning in resolved.warnings)


def test_resolve_uses_terminal_env_with_args():
    resolved = resolve_terminal(
        None,
        environ={"TERMINAL": "kitty --single-instance"},
        home=Path("/nonexistent"),
        which=make_which({"kitty"}),
    )
    assert resolved.name == "kitty"
    assert resolved.prefix_args == ("--single-instance",)
    assert resolved.command(SSH_ARGS) == [
        "/usr/bin/kitty",
        "--single-instance",
        "--hold",
        *SSH_ARGS,
    ]


def test_resolve_terminal_env_beats_kde_default(tmp_path):
    config = tmp_path / ".config"
    config.mkdir()
    (config / "kdeglobals").write_text(
        "[General]\nTerminalApplication=konsole\n", encoding="utf-8"
    )
    resolved = resolve_terminal(
        None,
        environ={"TERMINAL": "kitty"},
        home=tmp_path,
        which=make_which({"kitty", "konsole"}),
    )
    assert resolved.name == "kitty"


def test_resolve_reads_kde_default(tmp_path):
    config = tmp_path / ".config"
    config.mkdir()
    (config / "kdeglobals").write_text(
        "[General]\nTerminalApplication=kitty\n", encoding="utf-8"
    )
    resolved = resolve_terminal(
        None, environ={}, home=tmp_path, which=make_which({"kitty"})
    )
    assert resolved.name == "kitty"
    assert resolved.command(SSH_ARGS)[0] == "/usr/bin/kitty"


def test_resolve_maps_kde_desktop_ids(tmp_path):
    config = tmp_path / ".config"
    config.mkdir()
    (config / "kdeglobals").write_text(
        "[General]\nTerminalApplication=org.kde.konsole.desktop\n", encoding="utf-8"
    )
    resolved = resolve_terminal(
        None, environ={}, home=tmp_path, which=make_which({"konsole"})
    )
    assert resolved.name == "konsole"


def test_resolve_respects_xdg_config_home(tmp_path):
    config_home = tmp_path / "xdg"
    config_home.mkdir()
    (config_home / "kdeglobals").write_text(
        "[General]\nTerminalApplication=kitty\n", encoding="utf-8"
    )
    home = tmp_path / "home"
    home.mkdir()
    resolved = resolve_terminal(
        None,
        environ={"XDG_CONFIG_HOME": str(config_home)},
        home=home,
        which=make_which({"kitty"}),
    )
    assert resolved.name == "kitty"


def test_resolve_ignores_malformed_kdeglobals(tmp_path):
    config = tmp_path / ".config"
    config.mkdir()
    (config / "kdeglobals").write_text("not an ini file [[[", encoding="utf-8")
    resolved = resolve_terminal(
        None, environ={}, home=tmp_path, which=make_which({"xterm"})
    )
    assert resolved.name == "xterm"


def test_resolve_uses_fallback_order():
    resolved = resolve_terminal(
        None,
        environ={},
        home=Path("/nonexistent"),
        which=make_which({"xterm", "konsole"}),
    )
    assert resolved.name == "konsole"


def test_resolve_uses_xdg_terminal_exec():
    resolved = resolve_terminal(
        None,
        environ={},
        home=Path("/nonexistent"),
        which=make_which({"xdg-terminal-exec"}),
    )
    assert resolved.command(SSH_ARGS) == ["/usr/bin/xdg-terminal-exec", *SSH_ARGS]


def test_resolve_raises_when_no_terminal_exists():
    with pytest.raises(TerminalNotFoundError) as excinfo:
        resolve_terminal(None, environ={}, home=Path("/nonexistent"), which=make_which(set()))
    assert "No terminal emulator" in str(excinfo.value)


def test_open_terminal_spawns_detached(spawn, tmp_path):
    launched = open_terminal(
        SSH_ARGS, "system", environ={}, home=tmp_path, which=make_which({"kitty"})
    )

    argv, kwargs = spawn[0]
    assert argv == ["/usr/bin/kitty", "--hold", *SSH_ARGS]
    assert kwargs["start_new_session"] is True
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.DEVNULL
    assert launched.name == "kitty"
    assert launched.warnings == ()


def test_open_terminal_honours_configured_terminal(spawn, tmp_path):
    launched = open_terminal(
        SSH_ARGS,
        "xterm",
        environ={},
        home=tmp_path,
        which=make_which({"xterm", "kitty"}),
    )

    assert spawn[0][0] == ["/usr/bin/xterm", "-e", *SSH_ARGS]
    assert launched.name == "xterm"


def test_open_terminal_reports_which_preferences_were_skipped(spawn, tmp_path):
    # The connection asks for konsole, $TERMINAL names kitty, only xterm exists.
    launched = open_terminal(
        SSH_ARGS,
        "konsole",
        environ={"TERMINAL": "kitty"},
        home=tmp_path,
        which=make_which({"xterm"}),
    )

    assert launched.name == "xterm"
    assert any("konsole" in warning for warning in launched.warnings)
    assert any("$TERMINAL" in warning for warning in launched.warnings)
    assert spawn[0][0] == ["/usr/bin/xterm", "-e", *SSH_ARGS]


def test_spawn_environment_supplies_a_terminal_type(spawn, tmp_path):
    # An application started from the desktop menu has no TERM, and ssh
    # forwards TERM to the remote session.
    open_terminal(
        SSH_ARGS, "system", environ={}, home=tmp_path, which=make_which({"kitty"})
    )

    assert spawn[0][1]["env"]["TERM"] == "xterm-256color"


@pytest.mark.parametrize("term", ["dumb", "unknown", "", "  "])
def test_spawn_environment_replaces_unusable_terminal_types(spawn, tmp_path, term):
    open_terminal(
        SSH_ARGS,
        "system",
        environ={"TERM": term, "PATH": "/usr/bin"},
        home=tmp_path,
        which=make_which({"kitty"}),
    )

    env = spawn[0][1]["env"]
    assert env["TERM"] == "xterm-256color"
    # Everything else is passed through untouched.
    assert env["PATH"] == "/usr/bin"


@pytest.mark.parametrize("term", ["xterm-kitty", "xterm-256color", "foot"])
def test_spawn_environment_keeps_a_usable_terminal_type(spawn, tmp_path, term):
    open_terminal(
        SSH_ARGS,
        "system",
        environ={"TERM": term},
        home=tmp_path,
        which=make_which({"kitty"}),
    )

    assert spawn[0][1]["env"]["TERM"] == term


def test_open_terminal_wraps_launch_errors(monkeypatch, tmp_path):
    def raising(argv, **kwargs):
        raise FileNotFoundError("no such file")

    monkeypatch.setattr("ssh_manager.services.terminal.subprocess.Popen", raising)
    with pytest.raises(TerminalLaunchError):
        open_terminal(
            SSH_ARGS, "system", environ={}, home=tmp_path, which=make_which({"kitty"})
        )


def test_build_ssh_args_survive_terminal_wrapping():
    connection = Connection(
        name="x", hostname="example.com", username="user", port=2222, remote_command="htop"
    )
    args = ConnectionService.build_ssh_args(connection)
    command = build_command("kitty", args)
    assert command[:3] == ["kitty", "--hold", "ssh"]
    assert "user@example.com" in command
    assert command[-1] == "htop"
