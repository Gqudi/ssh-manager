# SSH Manager

v0.1.0 — a small PySide6/Qt Widgets SSH connection manager using SQLite and SQLAlchemy.

## Features

- Connect always opens a new terminal window: per-connection terminal, `$TERMINAL`, KDE's
  default terminal, `xdg-terminal-exec`, then common emulators
- OpenSSH argument builder (no shell-string construction)
- ProxyJump support
- Remote command support
- ForwardAgent, compression, X11 forwarding and ServerAliveInterval options
- Additional OpenSSH `-o` options
- `~/.ssh` private-key path selection

- Create, edit, duplicate and delete SSH connections
- UUIDv4 as immutable connection ID
- SQLite database stored in the platform's application-data directory
- Groups
- Search
- Import from `~/.ssh/config` and export back to it (wildcards, `Match` blocks and
  `Include` directives are skipped with a warning; unmapped directives are preserved as
  `-o` options)
- SSH agent / private-key / password authentication metadata
- Private-key path is stored, never the private key contents
- Passwords are not stored by v0.1
- Designed to work especially well on Linux/KDE

## Requirements

- Python 3.10+
- A working `ssh` client for Connect
- PySide6 and SQLAlchemy

## Linux setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m ssh_manager
```

Or:

```bash
.venv/bin/ssh-manager
```

On Arch Linux, you can also use the system Python environment if you prefer, but a virtual environment is recommended for development.

## Database

The application automatically creates its SQLite database in the OS application-data directory.

No database file is required in the repository.

## Security

v0.1 deliberately does not save SSH passwords or private-key contents. The private-key field stores only a filesystem path.

Password/key-passphrase keyring integration is planned for a later version. Exported
ssh_config files contain no secrets — only host names, users and key paths — and are
written with `0600` permissions.

## v0.1 limitations

The SSH session itself is delegated to the system `ssh` client and opened in a terminal. This keeps the first release small and lets OpenSSH handle interactive authentication, host-key checking, agent forwarding, etc.

The terminal is resolved per connection, then from `$TERMINAL`, KDE's
`TerminalApplication` setting, `xdg-terminal-exec`, and finally a list of common emulators
(konsole, kitty, gnome-terminal, kgx, xfce4-terminal, tilix, alacritty, foot, wezterm,
xterm). If no terminal is found, Connect reports an error instead of silently doing
nothing. konsole and kitty are started with `--hold` so failed connections stay readable.

Import/export notes: wildcard `Host` blocks, `Match` blocks and `Include` directives are
skipped with a warning rather than expanded; only the first `IdentityFile` is imported;
groups, notes and the terminal choice are not part of the ssh_config format and are not
exported.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest
```
