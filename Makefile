# SSH Manager — install as a desktop application.
#
#   make install                    # per-user, into ~/.local
#   sudo make install PREFIX=/usr   # system-wide
#   make uninstall                  # undo (pass the same PREFIX)
#   make run / make test / make lint / make check
#
# The install gets its own virtualenv. By default that venv can see the
# distribution's Python packages, so a distro PySide6/Qt is reused rather than
# downloaded and duplicated (~700 MB); pip still installs whatever is missing,
# such as SQLAlchemy. Use ISOLATED=1 for a fully self-contained venv.
#
# This is not a packaging tool: there is no DESTDIR support, because a venv
# bakes absolute paths into its scripts and cannot be staged into a build root.

PYTHON ?= python3
PREFIX ?= $(HOME)/.local

APPNAME    = ssh-manager
BINDIR     = $(PREFIX)/bin
APPSDIR    = $(PREFIX)/share/applications
ICONDIR    = $(PREFIX)/share/icons/hicolor/scalable/apps
# /usr-style prefixes keep the venv under lib/, per-user prefixes under share/.
ifeq ($(filter $(PREFIX),/usr /usr/local),$(PREFIX))
APPDIR     = $(PREFIX)/lib/$(APPNAME)
else
APPDIR     = $(PREFIX)/share/$(APPNAME)
endif
VENV       = $(APPDIR)/venv
LAUNCHER   = $(VENV)/bin/$(APPNAME)
DESKTOPSRC = packaging/$(APPNAME).desktop.in
DESKTOP    = build/$(APPNAME).desktop
ICONSRC    = src/ssh_manager/assets/$(APPNAME).svg
SOURCES    = $(shell find src -type f -not -path '*/__pycache__/*')

ifeq ($(ISOLATED),1)
VENV_FLAGS =
else
VENV_FLAGS = --system-site-packages
endif

# Refresh KDE's menu database, but only for a per-user install — running it
# under sudo would update root's cache instead of the logged-in user's.
ifeq ($(filter $(HOME)/%,$(PREFIX)),$(PREFIX))
REFRESH_KDE = 1
endif

.PHONY: install uninstall run test lint check clean

install: $(BINDIR)/$(APPNAME) $(APPSDIR)/$(APPNAME).desktop $(ICONDIR)/$(APPNAME).svg
	-@update-desktop-database $(APPSDIR) 2>/dev/null
	-@gtk-update-icon-cache -f -q -t $(PREFIX)/share/icons/hicolor 2>/dev/null
ifeq ($(REFRESH_KDE),1)
	-@kbuildsycoca6 --noincremental 2>/dev/null
endif
	@echo "Installed: $(BINDIR)/$(APPNAME)"
	@echo "'SSH Manager' is in the application menu (Internet -> Remote Access)."

uninstall:
	rm -f $(BINDIR)/$(APPNAME) $(APPSDIR)/$(APPNAME).desktop $(ICONDIR)/$(APPNAME).svg
	@case "$(APPDIR)" in *$(APPNAME)*) rm -rf "$(APPDIR)" ;; \
	  *) echo "refusing to delete unexpected path: $(APPDIR)" >&2; exit 1 ;; esac
	-@update-desktop-database $(APPSDIR) 2>/dev/null
ifeq ($(REFRESH_KDE),1)
	-@kbuildsycoca6 --noincremental 2>/dev/null
endif
	@echo "Removed $(APPNAME) from $(PREFIX)."

# --- application ------------------------------------------------------------

$(LAUNCHER): pyproject.toml $(SOURCES)
	$(PYTHON) -m venv $(VENV_FLAGS) $(VENV)
	$(VENV)/bin/python -m pip install --no-input --disable-pip-version-check \
		--no-warn-script-location $(CURDIR)

$(BINDIR)/$(APPNAME): $(LAUNCHER)
	@mkdir -p $(BINDIR)
	ln -sfn $(LAUNCHER) $@

$(DESKTOP): $(DESKTOPSRC)
	@mkdir -p $(dir $@)
	sed -e 's|@EXEC@|$(BINDIR)/$(APPNAME)|' -e 's|@ICON@|$(APPNAME)|' $< > $@
	@if command -v desktop-file-validate >/dev/null 2>&1; then desktop-file-validate $@; fi

$(APPSDIR)/$(APPNAME).desktop: $(DESKTOP)
	@mkdir -p $(APPSDIR)
	install -m644 $< $@

$(ICONDIR)/$(APPNAME).svg: $(ICONSRC)
	@mkdir -p $(ICONDIR)
	install -m644 $< $@

# --- development ------------------------------------------------------------

DEVPY = .venv/bin/python

$(DEVPY):
	$(PYTHON) -m venv --system-site-packages .venv
	$(DEVPY) -m pip install -e ".[dev]"

run: $(DEVPY)
	$(DEVPY) -m ssh_manager

test: $(DEVPY)
	$(DEVPY) -m pytest

lint: $(DEVPY)
	$(DEVPY) -m ruff check .
	$(DEVPY) -m mypy

check: lint test

clean:
	rm -rf build
