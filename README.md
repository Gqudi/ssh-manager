# SSH Manager

v0.1.0 — a small PySide6/Qt Widgets SSH connection manager using SQLite and SQLAlchemy.

## Features

- Connect always opens a new terminal window: per-connection terminal, `$TERMINAL`, KDE's
  default terminal, `xdg-terminal-exec`, then common emulators. When your preferred
  terminal is missing, the fallback is reported instead of passing unnoticed.
- OpenSSH argument builder (no shell-string construction)
- The authentication method selects the OpenSSH flags: agent (OpenSSH's default order),
  private key (the key is passed with `-i` and `IdentitiesOnly=yes`), or password
  (`PreferredAuthentications=password,keyboard-interactive`, public keys off)
- ProxyJump support
- Remote command support, run under a pseudo-terminal (`-t`), so screen programs
  such as `htop` or `tmux` get a TERM on the remote side. A connection whose extra
  options set `RequestTTY` keeps that choice instead.
- ForwardAgent, compression, X11 forwarding and ServerAliveInterval options
- Additional OpenSSH `-o` options; your own `-o` lines win over the app's defaults
- `~/.ssh` private-key path selection

- Create, edit, duplicate and delete SSH connections
- UUIDv4 as immutable connection ID
- SQLite database stored in the platform's application-data directory, with a schema
  version and automatic migrations (a copy is kept as `*.bak` before one runs)
- Groups
- Search across name, host, user, group, notes and key path
- Import from `~/.ssh/config` and export back to it (wildcards, `Match` blocks and
  `Include` directives are skipped with a warning; unmapped directives are preserved as
  `-o` options)
- Import conflicts are resolved per import: skip, overwrite, or import as a copy
- SSH agent / private-key / password authentication metadata
- Private-key path is stored, never the private key contents
- Passwords are not stored by v0.1
- A toolbar instead of a menu bar: Add/Import/Export as buttons, with Find, About and
  Quit in its overflow menu on the right
- Keyboard shortcuts throughout (Ctrl+N, Ctrl+E, Ctrl+D, Ctrl+F, Ctrl+Q, Ctrl+Shift+I/E,
  Enter to connect, Delete to delete); window layout and splitter position are remembered
- Designed to work especially well on Linux/KDE
- Installs as a desktop application: application-menu entry, icon and an
  `ssh-manager` launcher

## Requirements

- Python 3.10+
- A working `ssh` client for Connect
- PySide6 and SQLAlchemy

## Installation (Linux desktop)

```bash
make install
```

This installs into `~/.local` and adds **SSH Manager** to the application menu
(Internet → Remote Access; searchable as "SSH Manager" in KRunner and the launcher).
No root is needed:

| | |
|---|---|
| launcher | `~/.local/bin/ssh-manager` |
| desktop entry | `~/.local/share/applications/ssh-manager.desktop` |
| icon | `~/.local/share/icons/hicolor/scalable/apps/ssh-manager.svg` |
| virtualenv | `~/.local/share/ssh-manager/venv` |

For a system-wide install:

```bash
sudo make install PREFIX=/usr
```

Undo it with `make uninstall` (pass the same `PREFIX`). Your connections are stored in
the application-data directory and are **not** deleted.

The install builds a virtualenv that can see the distribution's Python packages, so a
distro PySide6/Qt is reused instead of downloaded and duplicated (~700 MB); pip still
installs anything missing, such as SQLAlchemy. Use `ISOLATED=1` for a self-contained
virtualenv that does not depend on distro packages:

```bash
make install ISOLATED=1
```

After editing the source, re-run `make install` to update the installed copy.

The install refreshes the desktop and icon caches, including KDE's. If the menu entry
still does not appear, log out and back in.

## Database

The application automatically creates its SQLite database in the OS application-data
directory; **About**, in the toolbar's overflow menu, shows the exact path. No database
file is required in the repository.

The schema carries a version (SQLite's `user_version`), and `Database.initialize()` applies
the migrations listed in `MIGRATIONS` when an older database is opened. Databases created
by v0.1 are recognised automatically. Before any migration runs, the file is copied next
to the original as `ssh-manager.sqlite3.v<version>.bak`; a database written by a *newer*
release is refused rather than silently downgraded. Schema changes go with a new
`Migration` entry and a matching `Database.SCHEMA_VERSION` bump — a startup check fails
loudly if the two disagree.

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
exported. When an imported name is already stored, the import dialog asks whether to skip
it, overwrite it (notes, group and terminal choice are kept) or import it as a copy.

### Terminal type (TERM)

The remote session runs with the `TERM` of the emulator that hosts it — kitty, for
instance, sets `xterm-kitty`, which a server only understands if kitty's terminfo is
installed there. If a remote program complains about an unknown terminal type, install
that terminfo on the server (`kitty-terminfo` on Arch, Debian and Ubuntu) or pin a
portable type for the connection by adding this line to its **Extra SSH options**:

```
SetEnv=TERM=xterm-256color
```

An application started from the desktop menu has no `TERM` at all; when the environment
carries none (or `dumb`/`unknown`), the terminal is started with `xterm-256color`.
Emulators that set their own type override that.

## Development

```bash
make run     # create .venv on first use, then run from source
make test    # run the test suite
make lint    # ruff + mypy
make check   # lint and tests
```

Or manually:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m mypy
```

The UI tests run headless (`QT_QPA_PLATFORM=offscreen`, set in `tests/conftest.py`) and
inject their own settings file, so they never read or write your configuration.
`.github/workflows/ci.yml` runs lint, type checks and the tests on Python 3.10, 3.13 and
3.14.

On Arch Linux, you can also use the system Python environment if you prefer, but a
virtual environment is recommended for development.
