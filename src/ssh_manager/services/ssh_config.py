"""Import from and export to OpenSSH ``ssh_config`` files.

The parser is deliberately conservative: it imports concrete ``Host`` blocks and
keeps every directive it cannot map to a modelled field as an extra ``-o``
option, so round-tripping a connection through ssh_config does not lose data.
Wildcard blocks, ``Match`` blocks and ``Include`` directives are skipped with a
warning instead of being guessed at.
"""

from __future__ import annotations

import getpass
import os
import re
import shlex
from dataclasses import dataclass, field
from typing import Iterable

from ..database.models import Connection

DEFAULT_PORT = 22

_MAPPED_KEYWORDS = frozenset(
    {
        "hostname",
        "user",
        "port",
        "identityfile",
        "proxyjump",
        "forwardagent",
        "compression",
        "forwardx11",
        "serveraliveinterval",
        "remotecommand",
    }
)

_TRUE_VALUES = frozenset({"yes", "true", "on", "1"})
_FALSE_VALUES = frozenset({"no", "false", "off", "0"})


@dataclass
class ImportedHost:
    """A single ``Host`` block, ready to be stored as a connection."""

    name: str
    hostname: str
    username: str
    port: int = DEFAULT_PORT
    auth_method: str = "agent"
    private_key: str | None = None
    proxy_jump: str | None = None
    forward_agent: bool = False
    compression: bool = False
    x11_forwarding: bool = False
    server_alive_interval: int = 0
    remote_command: str | None = None
    extra_options: list[str] = field(default_factory=list)
    warnings: tuple[str, ...] = ()

    def to_connection_kwargs(self) -> dict:
        return {
            "name": self.name,
            "hostname": self.hostname,
            "username": self.username,
            "port": self.port,
            "auth_method": self.auth_method,
            "private_key": self.private_key,
            "group_name": None,
            "notes": None,
            "forward_agent": self.forward_agent,
            "compression": self.compression,
            "x11_forwarding": self.x11_forwarding,
            "server_alive_interval": self.server_alive_interval,
            "proxy_jump": self.proxy_jump,
            "remote_command": self.remote_command,
            "extra_options": "\n".join(self.extra_options) or None,
            "terminal": "system",
        }


@dataclass
class ParseReport:
    hosts: list[ImportedHost] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ImportSummary:
    imported: int = 0
    overwritten: int = 0
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- parsing


def _logical_lines(text: str) -> list[str]:
    """Split into lines, honouring backslash continuation."""
    lines: list[str] = []
    buffer = ""
    for raw in text.splitlines():
        raw = raw.rstrip("\r")
        if buffer:
            raw = buffer + raw.lstrip()
            buffer = ""
        if raw.rstrip().endswith("\\") and not raw.lstrip().startswith("#"):
            buffer = raw.rstrip()[:-1]
            continue
        lines.append(raw)
    if buffer:
        lines.append(buffer)
    return lines


def _split_directive(line: str) -> tuple[str, str] | None:
    """Split ``Keyword value`` / ``Keyword=value``; returns None for comments."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    match = re.match(r"([^\s=]+)\s*(?:=\s*)?(.*)", stripped)
    if not match:
        return None
    return match.group(1), match.group(2).strip()


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


def _parse_patterns(value: str) -> list[str]:
    try:
        return shlex.split(value)
    except ValueError:
        return value.split()


def _is_wildcard(pattern: str) -> bool:
    return pattern.startswith("!") or any(char in pattern for char in "*?[")


def _boolean(raw: str | None, label: str, warnings: list[str]) -> bool:
    if raw is None:
        return False
    lowered = raw.lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    warnings.append(f"{label}: '{raw}' is not a valid yes/no value; assuming no.")
    return False


def _integer(raw: str | None, default: int, label: str, warnings: list[str]) -> int:
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        warnings.append(f"{label}: '{raw}' is not a number; using {default}.")
        return default


def _none_if_disabled(raw: str | None) -> str | None:
    if raw is None or raw.lower() == "none":
        return None
    return raw


def _build_host(alias: str, options: list[tuple[str, str]], default_user: str) -> ImportedHost:
    warnings: list[str] = []

    def first(keyword: str) -> str | None:
        for option_keyword, value in options:
            if option_keyword.lower() == keyword:
                return value
        return None

    identity_count = sum(1 for keyword, _ in options if keyword.lower() == "identityfile")
    identity = first("identityfile")
    private_key: str | None = None
    auth_method = "agent"
    if identity and identity.lower() != "none":
        private_key = os.path.expanduser(identity)
        auth_method = "key"
    if identity_count > 1:
        warnings.append(
            f"'{alias}': only the first IdentityFile is imported ({identity_count} found)."
        )

    return ImportedHost(
        name=alias,
        hostname=first("hostname") or alias,
        username=first("user") or default_user,
        port=_integer(first("port"), DEFAULT_PORT, f"Port for '{alias}'", warnings),
        auth_method=auth_method,
        private_key=private_key,
        proxy_jump=_none_if_disabled(first("proxyjump")),
        forward_agent=_boolean(first("forwardagent"), f"ForwardAgent for '{alias}'", warnings),
        compression=_boolean(first("compression"), f"Compression for '{alias}'", warnings),
        x11_forwarding=_boolean(first("forwardx11"), f"ForwardX11 for '{alias}'", warnings),
        server_alive_interval=_integer(
            first("serveraliveinterval"), 0, f"ServerAliveInterval for '{alias}'", warnings
        ),
        remote_command=_none_if_disabled(first("remotecommand")),
        extra_options=[
            f"{keyword}={value if value else 'yes'}"
            for keyword, value in options
            if keyword.lower() not in _MAPPED_KEYWORDS
        ],
        warnings=tuple(warnings),
    )


def parse_ssh_config_report(text: str, *, username: str | None = None) -> ParseReport:
    """Parse ssh_config text into importable hosts plus file-level warnings."""
    default_user = username or getpass.getuser()
    report = ParseReport()

    defaults: list[tuple[str, str]] = []
    block: list[tuple[str, str]] = []
    patterns: list[str] = []
    seen_aliases: set[str] = set()
    in_match = False

    def flush() -> None:
        nonlocal block, patterns
        if patterns:
            options = [*defaults, *block]
            for alias in patterns:
                if _is_wildcard(alias):
                    report.warnings.append(f"Skipped wildcard host pattern '{alias}'.")
                    continue
                if alias.lower() in seen_aliases:
                    report.warnings.append(f"Duplicate host alias '{alias}' ignored.")
                    continue
                seen_aliases.add(alias.lower())
                report.hosts.append(_build_host(alias, options, default_user))
        block = []
        patterns = []

    for line in _logical_lines(text):
        parsed = _split_directive(line)
        if parsed is None:
            continue
        keyword, value = parsed
        lowered = keyword.lower()

        if lowered == "host":
            flush()
            in_match = False
            patterns = _parse_patterns(value)
            continue
        if lowered == "match":
            flush()
            in_match = True
            report.warnings.append(f"Ignored Match block ('{value}').")
            continue
        if lowered == "include":
            report.warnings.append(f"Ignored Include directive ('{value}').")
            continue
        if in_match:
            continue

        entry = (keyword, _unquote(value))
        if patterns:
            block.append(entry)
        else:
            defaults.append(entry)

    flush()
    return report


def parse_ssh_config(text: str, username: str | None = None) -> list[ImportedHost]:
    """Parse ssh_config text into importable hosts."""
    return parse_ssh_config_report(text, username=username).hosts


# --------------------------------------------------------------------------- serialization

_ALIAS_UNSAFE = re.compile(r"[\s*?\[!]+")


def sanitize_alias(name: str) -> str:
    """Turn a connection name into a safe ``Host`` alias."""
    alias = _ALIAS_UNSAFE.sub("-", name.strip()).strip("-")
    return alias or "host"


def _clean(value: str) -> str:
    return " ".join(value.split())


def _unique_alias(alias: str, used: set[str]) -> str:
    candidate = alias
    counter = 2
    while candidate.lower() in used:
        candidate = f"{alias}-{counter}"
        counter += 1
    used.add(candidate.lower())
    return candidate


def serialize_connections(connections: Iterable[Connection]) -> str:
    """Render connections as an ssh_config file."""
    blocks: list[str] = []
    used_aliases: set[str] = set()

    for connection in connections:
        alias = _unique_alias(sanitize_alias(connection.name), used_aliases)
        lines = [
            f"Host {alias}",
            f"    HostName {_clean(connection.hostname)}",
            f"    User {_clean(connection.username)}",
        ]
        if (connection.port or DEFAULT_PORT) != DEFAULT_PORT:
            lines.append(f"    Port {connection.port}")
        if connection.auth_method == "key" and connection.private_key:
            lines.append(f"    IdentityFile {_clean(connection.private_key)}")
        if connection.proxy_jump:
            lines.append(f"    ProxyJump {_clean(connection.proxy_jump)}")
        if connection.forward_agent:
            lines.append("    ForwardAgent yes")
        if connection.compression:
            lines.append("    Compression yes")
        if connection.x11_forwarding:
            lines.append("    ForwardX11 yes")
        if (connection.server_alive_interval or 0) > 0:
            lines.append(f"    ServerAliveInterval {connection.server_alive_interval}")
        if connection.remote_command:
            lines.append(f"    RemoteCommand {_clean(connection.remote_command)}")
        for line in (connection.extra_options or "").splitlines():
            line = line.strip()
            if line:
                lines.append(f"    {line}")
        blocks.append("\n".join(lines))

    header = "# Generated by SSH Manager"
    if not blocks:
        return header + "\n"
    return header + "\n\n" + "\n\n".join(blocks) + "\n"
