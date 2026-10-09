"""UI behaviour of the main window, running headless.

The settings object is injected, so these tests never touch the user's real
configuration, and no window is ever shown: the offscreen platform plugin is
selected in conftest.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QDialog, QMenuBar, QMessageBox, QToolBar

from ssh_manager.database.database import Database
from ssh_manager.services.connection_service import ConnectionService
from ssh_manager.services.terminal import LaunchedTerminal, TerminalNotFoundError
from ssh_manager.ui.main_window import MainWindow


@pytest.fixture
def settings(tmp_path: Path) -> QSettings:
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


@pytest.fixture
def window(qapp, database: Database, settings: QSettings):
    window = MainWindow(database, settings=settings)
    yield window
    window.search_timer.stop()
    window.close()


def create(service: ConnectionService, name: str, **overrides):
    data = {"name": name, "hostname": f"{name.lower()}.example.com", "username": "user"}
    data.update(overrides)
    return service.create(**data)


# ------------------------------------------------------------------ details pane


def test_details_escape_user_input(window: MainWindow, service: ConnectionService) -> None:
    create(
        service,
        "Prod",
        notes="keep in mind: a < b & <b>bold</b>",
    )
    window.reload_connections()

    text = window.details_label.text()

    assert "a &lt; b &amp;" in text
    assert "&lt;b&gt;bold&lt;/b&gt;" in text
    assert "<b>bold</b>" not in text


def test_details_keep_note_line_breaks(window: MainWindow, service: ConnectionService) -> None:
    create(service, "Prod", notes="first line\nsecond line")
    window.reload_connections()

    assert "first line<br>second line" in window.details_label.text()


def test_clear_details_explains_the_empty_list(window: MainWindow) -> None:
    assert "Ctrl+N" in window.details_label.text()


# ------------------------------------------------------------------ list and search


def test_search_filters_and_is_debounced(
    window: MainWindow, service: ConnectionService
) -> None:
    create(service, "Prod")
    create(service, "Staging")
    window.reload_connections()
    assert window.connection_list.count() == 2

    window.search.setText("stag")
    assert window.search_timer.isActive(), "typing must not query per keystroke"

    window.reload_connections()
    assert window.connection_list.count() == 1
    assert "Staging" in window.connection_list.item(0).text()
    assert window.count_label.text() == "1 connection of 2"


def test_search_matches_notes_too(window: MainWindow, service: ConnectionService) -> None:
    create(service, "Prod", notes="only reachable via the VPN")
    create(service, "Other")
    window.reload_connections()

    window.search.setText("vpn")
    window.reload_connections()

    assert window.connection_list.count() == 1
    assert "Prod" in window.connection_list.item(0).text()


def test_select_by_id_marks_the_row(window: MainWindow, service: ConnectionService) -> None:
    first = create(service, "Aaa")
    second = create(service, "Bbb")
    window.reload_connections()

    window.select_by_id(second.id)

    assert window.selected_id() == second.id
    assert window.selected_id() != first.id


# ------------------------------------------------------------------ actions


class FakeConnectionDialog:
    """Stands in for ConnectionDialog: saves a fixed connection when accepted."""

    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs

    def exec(self) -> QDialog.DialogCode:
        return QDialog.DialogCode.Accepted

    def data(self) -> dict:
        return {"name": "Added", "hostname": "added.example.com", "username": "user"}


def test_add_connection_selects_the_new_connection(
    window: MainWindow, monkeypatch
) -> None:
    monkeypatch.setattr(
        "ssh_manager.ui.main_window.ConnectionDialog", FakeConnectionDialog
    )

    window.add_connection()

    selected = window.selected_connection()
    assert selected is not None
    assert selected.name == "Added"
    assert window.title_label.text() == "Added"


def test_duplicate_selects_the_copy(window: MainWindow, service: ConnectionService) -> None:
    original = create(service, "Prod")
    window.reload_connections()
    window.select_by_id(original.id)

    window.duplicate_selected()

    selected = window.selected_connection()
    assert selected is not None
    assert selected.name == "Prod (Copy)"


def test_deleting_asks_for_confirmation(
    window: MainWindow, service: ConnectionService, monkeypatch
) -> None:
    connection = create(service, "Prod")
    window.reload_connections()
    window.select_by_id(connection.id)

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No
    )
    window.delete_selected()
    assert service.get(connection.id) is not None

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    window.delete_selected()
    assert service.get(connection.id) is None


def test_connect_reports_the_terminal_and_its_warnings(
    window: MainWindow, service: ConnectionService, monkeypatch
) -> None:
    create(service, "Prod")
    window.reload_connections()

    monkeypatch.setattr(
        window.service,
        "connect",
        lambda connection: LaunchedTerminal(
            name="xterm", warnings=("$TERMINAL ('kitty') was not found",)
        ),
    )

    window.connect_button.click()

    message = window.status.currentMessage()
    assert "xterm" in message
    assert "$TERMINAL ('kitty') was not found" in message


def test_connect_reports_a_missing_terminal(
    window: MainWindow, service: ConnectionService, monkeypatch
) -> None:
    create(service, "Prod")
    window.reload_connections()

    def fail(connection):
        del connection
        raise TerminalNotFoundError("No terminal emulator was found")

    warnings: list[str] = []
    monkeypatch.setattr(window.service, "connect", fail)
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args)
    )

    window.connect_button.click()

    assert any("No terminal emulator" in " ".join(map(str, args)) for args in warnings)


def test_connect_and_delete_shortcuts_are_row_scoped(window: MainWindow) -> None:
    # They must not fire while the search field has focus.
    shortcuts = {
        shortcut.key().toString(): shortcut.context() for shortcut in window.list_shortcuts
    }

    assert {"Return", "Enter", "Del"} <= set(shortcuts)
    assert set(shortcuts.values()) == {Qt.ShortcutContext.WidgetShortcut}


def test_there_is_no_menu_bar(window: MainWindow) -> None:
    # The toolbar is the command surface; a menu bar would only repeat it.
    assert window.findChild(QMenuBar) is None


def test_toolbar_holds_the_primary_commands(window: MainWindow) -> None:
    toolbar = window.findChild(QToolBar)
    assert toolbar is not None

    texts = [action.text() for action in toolbar.actions()]
    assert texts[:3] == ["&Add…", "&Import…", "&Export…"]


def test_every_shortcut_is_attached_to_a_widget(window: MainWindow) -> None:
    """Removing the menu bar must not leave an action without a shortcut host."""
    toolbar = window.findChild(QToolBar)
    assert toolbar is not None

    attached = [*window.actions(), *toolbar.actions()]
    shortcuts = {
        action.shortcut().toString()
        for action in attached
        if not action.shortcut().isEmpty()
    }

    assert shortcuts == {
        "Ctrl+N",
        "Ctrl+E",
        "Ctrl+D",
        "Ctrl+F",
        "Ctrl+Q",
        "Ctrl+Shift+I",
        "Ctrl+Shift+E",
    }
    # Everything the overflow menu offers is wired up on the window too.
    for action in (window.find_action, window.about_action, window.quit_action):
        assert action in attached


def test_actions_follow_the_selection(window: MainWindow, service: ConnectionService) -> None:
    assert not window.connect_action.isEnabled()
    create(service, "Prod")
    window.reload_connections()
    assert window.connect_action.isEnabled()

    window.search.setText("no such connection")
    window.reload_connections()
    assert not window.connect_action.isEnabled()


# ------------------------------------------------------------------ window state


def test_layout_is_persisted(window: MainWindow, settings: QSettings) -> None:
    window.close()

    # Read back through a fresh object, so the values must have reached the file.
    stored = QSettings(settings.fileName(), QSettings.Format.IniFormat)
    assert stored.value("window/geometry") is not None
    assert stored.value("window/splitter") is not None


def test_a_saved_layout_is_restored(qapp, database: Database, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)

    first = MainWindow(database, settings=settings)
    # The offscreen screen is 800x800, so use a size that fits into it.
    first.resize(800, 560)
    first.close()

    second = MainWindow(database, settings=settings)
    try:
        # Without the restore this would still be the 1000x650 default.
        assert (second.width(), second.height()) == (800, 560)
    finally:
        second.search_timer.stop()
        second.close()
