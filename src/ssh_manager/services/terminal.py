"""Resolution and launching of terminal emulators.

The connection manager never runs ``ssh`` directly: doing so only works when the
application itself was started from a terminal, and fails silently when it was
started from an application launcher.  Instead every connection is opened in a
new terminal window, using the per-connection setting, ``$TERMINAL`` or the
desktop's configured default terminal, in that order.
"""

from __future__ import annotations

import configparser
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


class TerminalError(RuntimeError):
    """Base class for problems while opening a terminal emulator."""


class TerminalNotFoundError(TerminalError):
    """No usable terminal emulator was found."""


class TerminalLaunchError(TerminalError):
    """A terminal emulator was found but could not be started."""


#: Terminal type used when the environment does not carry a usable one.  An
#: application started from the desktop menu has no TERM at all, and ssh
#: forwards TERM to the remote session, where ncurses needs it.
FALLBACK_TERM = "xterm-256color"

#: TERM values the remote side can make no sense of.
_UNUSABLE_TERMS = frozenset({"", "unknown", "dumb"})

#: Terminals offered in the connection dialog and used as detection fallbacks,
#: in order of preference.
SUPPORTED_TERMINALS: tuple[str, ...] = (
    "konsole",
    "kitty",
    "gnome-terminal",
    "kgx",
    "xfce4-terminal",
    "tilix",
    "alacritty",
    "foot",
    "wezterm",
    "xterm",
)

#: Maps freedesktop desktop-entry IDs (as stored by KDE's TerminalApplication
#: setting) to executable names.
_DESKTOP_IDS: dict[str, str] = {
    "org.kde.konsole.desktop": "konsole",
    "konsole.desktop": "konsole",
    "org.gnome.terminal.desktop": "gnome-terminal",
    "gnome-terminal.desktop": "gnome-terminal",
    "org.gnome.kgx.desktop": "kgx",
    "kgx.desktop": "kgx",
    "kitty.desktop": "kitty",
    "alacritty.desktop": "alacritty",
    "foot.desktop": "foot",
    "org.wezfurlong.wezterm.desktop": "wezterm",
    "wezterm.desktop": "wezterm",
    "xfce4-terminal.desktop": "xfce4-terminal",
    "tilix.desktop": "tilix",
    "xterm.desktop": "xterm",
}


def _build_direct(executable: str, prefix: Sequence[str], ssh_args: Sequence[str]) -> list[str]:
    return [executable, *prefix, *ssh_args]


def _build_dash_e(executable: str, prefix: Sequence[str], ssh_args: Sequence[str]) -> list[str]:
    return [executable, *prefix, "-e", *ssh_args]


def _build_dashdash(executable: str, prefix: Sequence[str], ssh_args: Sequence[str]) -> list[str]:
    return [executable, *prefix, "--", *ssh_args]


def _build_kitty(executable: str, prefix: Sequence[str], ssh_args: Sequence[str]) -> list[str]:
    # kitty [options] [program-to-run ...]; --hold keeps failed connections readable
    return [executable, *prefix, "--hold", *ssh_args]


def _build_konsole(executable: str, prefix: Sequence[str], ssh_args: Sequence[str]) -> list[str]:
    return [executable, *prefix, "--hold", "-e", *ssh_args]


def _build_command_argument(
    executable: str, prefix: Sequence[str], ssh_args: Sequence[str]
) -> list[str]:
    return [executable, *prefix, "--command", shlex.join(ssh_args)]


def _build_execute_argument(
    executable: str, prefix: Sequence[str], ssh_args: Sequence[str]
) -> list[str]:
    return [executable, *prefix, "-e", shlex.join(ssh_args)]


def _build_wezterm(executable: str, prefix: Sequence[str], ssh_args: Sequence[str]) -> list[str]:
    return [executable, *prefix, "start", "--", *ssh_args]


_BUILDERS: dict[str, Callable[[str, Sequence[str], Sequence[str]], list[str]]] = {
    "konsole": _build_konsole,
    "kitty": _build_kitty,
    "gnome-terminal": _build_dashdash,
    "kgx": _build_dashdash,
    "xfce4-terminal": _build_command_argument,
    "tilix": _build_execute_argument,
    "alacritty": _build_dash_e,
    "foot": _build_direct,
    "wezterm": _build_wezterm,
    "xterm": _build_dash_e,
    "xdg-terminal-exec": _build_direct,
}


def build_command(
    executable: str,
    ssh_args: Sequence[str],
    prefix_args: Sequence[str] = (),
) -> list[str]:
    """Build the argv that starts ``ssh_args`` inside the given terminal.

    Unknown executables fall back to the widely supported
    ``<terminal> -e ssh ...`` form.
    """
    builder = _BUILDERS.get(Path(executable).name, _build_dash_e)
    return builder(executable, list(prefix_args), list(ssh_args))


@dataclass(frozen=True)
class ResolvedTerminal:
    """A terminal emulator chosen for a connection."""

    name: str
    executable: str
    prefix_args: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def command(self, ssh_args: Sequence[str]) -> list[str]:
        return build_command(self.executable, ssh_args, self.prefix_args)


@dataclass(frozen=True)
class LaunchedTerminal:
    """A terminal emulator that was started, and how it was chosen."""

    name: str
    warnings: tuple[str, ...] = ()


def _split_command(value: str) -> list[str]:
    try:
        return shlex.split(value)
    except ValueError:
        return value.split()


def _resolve_desktop_id(token: str) -> str:
    name = Path(token).name
    mapped = _DESKTOP_IDS.get(name.lower())
    if mapped:
        return mapped
    if name.lower().endswith(".desktop"):
        return name[: -len(".desktop")]
    return token


def _kde_terminal(environ: Mapping[str, str], home: Path) -> str | None:
    config_home = environ.get("XDG_CONFIG_HOME") or str(home / ".config")
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(Path(config_home) / "kdeglobals", encoding="utf-8")
        value = parser.get("General", "TerminalApplication", fallback="").strip()
    except (OSError, configparser.Error):
        return None
    return value or None


def resolve_terminal(
    preferred: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    which: Callable[[str], str | None] | None = None,
) -> ResolvedTerminal:
    """Pick the terminal to use, in order of precedence:

    per-connection setting, ``$TERMINAL``, KDE's ``TerminalApplication``,
    ``xdg-terminal-exec``, then the :data:`SUPPORTED_TERMINALS` fallbacks.
    """
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)
    which = shutil.which if which is None else which

    warnings: list[str] = []

    def found(name: str, prefix: Sequence[str] = ()) -> ResolvedTerminal | None:
        executable = which(name)
        if not executable:
            return None
        return ResolvedTerminal(
            name=Path(name).name,
            executable=executable,
            prefix_args=tuple(prefix),
            warnings=tuple(warnings),
        )

    preferred = (preferred or "").strip()
    if preferred and preferred != "system":
        resolved = found(preferred)
        if resolved:
            return resolved
        warnings.append(
            f"Configured terminal '{preferred}' was not found; using the system default."
        )

    env_terminal = (environ.get("TERMINAL") or "").strip()
    if env_terminal:
        tokens = _split_command(env_terminal)
        executable = _resolve_desktop_id(tokens[0])
        resolved = found(executable, tokens[1:])
        if resolved:
            return resolved
        warnings.append(f"$TERMINAL ('{env_terminal}') was not found; using another terminal.")

    kde_terminal = _kde_terminal(environ, home)
    if kde_terminal:
        tokens = _split_command(kde_terminal)
        executable = _resolve_desktop_id(tokens[0])
        resolved = found(executable, tokens[1:])
        if resolved:
            return resolved
        warnings.append(
            f"The KDE default terminal ('{kde_terminal}') was not found; using another terminal."
        )

    resolved = found("xdg-terminal-exec")
    if resolved:
        return resolved

    for candidate in SUPPORTED_TERMINALS:
        resolved = found(candidate)
        if resolved:
            return resolved

    tried = ", ".join(SUPPORTED_TERMINALS)
    message = (
        "No terminal emulator was found. Install one of: "
        f"{tried}. You can also set $TERMINAL or choose a terminal in the "
        "connection's Terminal tab."
    )
    if warnings:
        message += " " + " ".join(warnings)
    raise TerminalNotFoundError(message)


def _child_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """The environment for the spawned terminal, with a usable ``TERM``.

    Terminals that set their own terminal type (kitty, for instance) override
    this anyway; it matters for those that pass the environment through, where
    an unset TERM would reach the remote session and break screen programs.
    """
    env = dict(environ)
    if env.get("TERM", "").strip().lower() in _UNUSABLE_TERMS:
        env["TERM"] = FALLBACK_TERM
    return env


def _spawn(argv: Sequence[str], env: Mapping[str, str]) -> subprocess.Popen:
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "env": dict(env),
    }
    if os.name == "posix":
        # Detach so the terminal window survives the connection manager exiting.
        kwargs["start_new_session"] = True
    try:
        return subprocess.Popen(list(argv), **kwargs)
    except OSError as exc:
        raise TerminalLaunchError(f"Could not start '{argv[0]}': {exc}") from exc


def open_terminal(
    ssh_args: Sequence[str],
    terminal: str = "system",
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    which: Callable[[str], str | None] | None = None,
    platform: str | None = None,
) -> LaunchedTerminal:
    """Open a new terminal window running the given ``ssh`` command.

    Returns the terminal that was actually started, including any warnings
    about configured terminals that had to be skipped, so callers can tell the
    user when their preference was not available.
    """
    ssh_args = list(ssh_args)
    platform = sys.platform if platform is None else platform
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)
    which = shutil.which if which is None else which
    env = _child_environment(environ)

    preferred = (terminal or "").strip()
    if preferred and preferred != "system":
        executable = which(preferred)
        if executable:
            _spawn(build_command(executable, ssh_args), env)
            return LaunchedTerminal(name=Path(executable).name)

    if platform == "darwin" and which("osascript"):
        script = f'tell application "Terminal" to do script {shlex.join(ssh_args)!r}'
        _spawn(["osascript", "-e", script], env)
        return LaunchedTerminal(name="Terminal.app")

    if platform.startswith("win") and which("wt"):
        _spawn(["wt", *ssh_args], env)
        return LaunchedTerminal(name="wt")

    resolved = resolve_terminal(
        preferred if preferred != "system" else None,
        environ=environ,
        home=home,
        which=which,
    )
    _spawn(resolved.command(ssh_args), env)
    return LaunchedTerminal(name=resolved.name, warnings=resolved.warnings)
