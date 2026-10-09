from __future__ import annotations

import os
from html import escape
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer, qVersion
from PySide6.QtGui import QAction, QCloseEvent, QFont, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..database.database import Database
from ..database.models import Connection
from ..services.connection_service import ConnectionService
from ..services.ssh_config import parse_ssh_config_report
from ..services.terminal import TerminalError, TerminalNotFoundError, resolve_terminal
from .connection_dialog import ConnectionDialog
from .import_dialog import ImportPreviewDialog

#: Typing in the search field should not run a query per keystroke.
SEARCH_DEBOUNCE_MS = 150


def _theme_icon(*names: str) -> QIcon:
    """The first of ``names`` that exists in the desktop's icon theme.

    Returns a null icon when the theme has none of them; widgets then simply
    show their text.
    """
    for name in names:
        icon = QIcon.fromTheme(name)
        if not icon.isNull():
            return icon
    return QIcon()


class MainWindow(QMainWindow):
    def __init__(self, database: Database, settings: QSettings | None = None) -> None:
        super().__init__()

        self.database = database
        self.service = ConnectionService(database)
        self.settings = QSettings() if settings is None else settings
        self.connections: list[Connection] = []

        self.setWindowTitle("SSH Manager")
        self.resize(1000, 650)
        self.setMinimumSize(800, 500)

        self.build_ui()
        self.build_actions()
        self.restore_layout()
        self.reload_connections()

    # ------------------------------------------------------------------ widgets

    def build_ui(self) -> None:
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search connections…")
        self.search.setClearButtonEnabled(True)
        self.search.setToolTip("Filter by name, host, user, group, key or notes (Ctrl+F)")

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self.search_timer.timeout.connect(self.reload_connections)
        self.search.textChanged.connect(self.schedule_reload)

        self.connection_list = QListWidget()
        self.connection_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.connection_list.setToolTip("Double-click or press Enter to connect")
        self.connection_list.currentItemChanged.connect(self.selection_changed)
        self.connection_list.itemDoubleClicked.connect(lambda _: self.connect_selected())

        # Row-scoped shortcuts: while the search field has focus, Enter and
        # Delete must stay with the text editor instead of connecting/deleting.
        self.list_shortcuts: list[QShortcut] = []
        for sequence, handler in (
            (QKeySequence(Qt.Key.Key_Return), self.connect_selected),
            (QKeySequence(Qt.Key.Key_Enter), self.connect_selected),
            (QKeySequence(QKeySequence.StandardKey.Delete), self.delete_selected),
        ):
            shortcut = QShortcut(sequence, self.connection_list)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(handler)
            self.list_shortcuts.append(shortcut)

        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.addWidget(self.search)
        sidebar_layout.addWidget(self.connection_list)

        self.details_frame = QFrame()
        details_layout = QVBoxLayout(self.details_frame)

        self.title_label = QLabel("No connection selected")
        title_font = QFont(self.font())
        title_font.setWeight(QFont.Weight.DemiBold)
        if title_font.pointSizeF() > 0:
            title_font.setPointSizeF(title_font.pointSizeF() * 1.5)
        self.title_label.setFont(title_font)

        self.details_label = QLabel()
        self.details_label.setTextFormat(Qt.TextFormat.RichText)
        self.details_label.setWordWrap(True)

        button_row = QHBoxLayout()

        self.connect_button = QPushButton(
            _theme_icon("network-connect", "go-next"), "Connect"
        )
        self.connect_button.setToolTip("Open this connection in a terminal (Enter)")
        self.edit_button = QPushButton(_theme_icon("edit-rename", "document-edit"), "Edit")
        self.edit_button.setToolTip("Edit this connection (Ctrl+E)")
        self.duplicate_button = QPushButton(_theme_icon("edit-copy"), "Duplicate")
        self.duplicate_button.setToolTip("Create an independent copy (Ctrl+D)")
        self.delete_button = QPushButton(_theme_icon("edit-delete"), "Delete")
        self.delete_button.setToolTip("Delete this connection (Delete)")

        self.connect_button.clicked.connect(self.connect_selected)
        self.edit_button.clicked.connect(self.edit_selected)
        self.duplicate_button.clicked.connect(self.duplicate_selected)
        self.delete_button.clicked.connect(self.delete_selected)

        self.detail_buttons = (
            self.connect_button,
            self.edit_button,
            self.duplicate_button,
            self.delete_button,
        )
        for button in self.detail_buttons:
            button_row.addWidget(button)
        button_row.addStretch()

        details_layout.addWidget(self.title_label)
        details_layout.addSpacing(12)
        details_layout.addWidget(self.details_label)
        details_layout.addStretch()
        details_layout.addLayout(button_row)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(sidebar)
        self.splitter.addWidget(self.details_frame)
        self.splitter.setSizes([300, 700])

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.splitter)

        self.setCentralWidget(central)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.count_label = QLabel()
        self.status.addPermanentWidget(self.count_label)

    def build_actions(self) -> None:
        self.add_action = QAction(_theme_icon("list-add"), "&Add…", self)
        self.add_action.setShortcut(QKeySequence.StandardKey.New)
        self.add_action.triggered.connect(self.add_connection)

        self.import_action = QAction(_theme_icon("document-import"), "&Import…", self)
        self.import_action.setToolTip("Import connections from an SSH config file")
        self.import_action.setShortcut(QKeySequence("Ctrl+Shift+I"))
        self.import_action.triggered.connect(self.import_ssh_config)

        self.export_action = QAction(_theme_icon("document-export"), "&Export…", self)
        self.export_action.setToolTip("Export connections to an SSH config file")
        self.export_action.setShortcut(QKeySequence("Ctrl+Shift+E"))
        self.export_action.triggered.connect(self.export_ssh_config)

        self.quit_action = QAction("&Quit", self)
        # Qt binds StandardKey.Quit on macOS only; everywhere else the
        # conventional Ctrl+Q has to be spelled out.
        quit_sequence = QKeySequence(QKeySequence.StandardKey.Quit)
        self.quit_action.setShortcut(
            quit_sequence if not quit_sequence.isEmpty() else QKeySequence("Ctrl+Q")
        )
        self.quit_action.triggered.connect(self.close)

        self.connect_action = QAction(_theme_icon("network-connect", "go-next"), "&Connect", self)
        self.connect_action.setToolTip("Open the selected connection (Enter)")
        self.connect_action.triggered.connect(self.connect_selected)

        self.edit_action = QAction(_theme_icon("edit-rename", "document-edit"), "&Edit…", self)
        self.edit_action.setShortcut(QKeySequence("Ctrl+E"))
        self.edit_action.triggered.connect(self.edit_selected)

        self.duplicate_action = QAction(_theme_icon("edit-copy"), "&Duplicate", self)
        self.duplicate_action.setShortcut(QKeySequence("Ctrl+D"))
        self.duplicate_action.triggered.connect(self.duplicate_selected)

        self.delete_action = QAction(_theme_icon("edit-delete"), "De&lete", self)
        self.delete_action.triggered.connect(self.delete_selected)

        self.find_action = QAction(_theme_icon("edit-find"), "&Find", self)
        self.find_action.setShortcut(QKeySequence.StandardKey.Find)
        self.find_action.triggered.connect(self.focus_search)

        self.about_action = QAction("&About SSH Manager", self)
        self.about_action.triggered.connect(self.show_about)

        self.selection_actions = (
            self.connect_action,
            self.edit_action,
            self.duplicate_action,
            self.delete_action,
        )
        self.set_selection_actions_enabled(False)

        # There is no menu bar, so the shortcuts live on the window itself; the
        # toolbar actions are already reachable through the toolbar.
        for action in (
            self.connect_action,
            self.edit_action,
            self.duplicate_action,
            self.delete_action,
            self.find_action,
            self.quit_action,
            self.about_action,
        ):
            self.addAction(action)

        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.addAction(self.add_action)
        toolbar.addAction(self.import_action)
        toolbar.addAction(self.export_action)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        toolbar.addWidget(self.build_overflow_button())
        self.addToolBar(toolbar)

    def build_overflow_button(self) -> QToolButton:
        """The toolbar's menu: the actions that do not deserve a button."""
        menu = QMenu(self)
        menu.addAction(self.find_action)
        menu.addSeparator()
        menu.addAction(self.about_action)
        menu.addAction(self.quit_action)

        button = QToolButton(self)
        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        icon = _theme_icon("application-menu", "open-menu-symbolic")
        if icon.isNull():
            button.setText("Menu")
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        else:
            button.setIcon(icon)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.setToolTip("More actions")
        return button

    # ------------------------------------------------------------------ window state

    def restore_layout(self) -> None:
        geometry = self.settings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        splitter_state = self.settings.value("window/splitter")
        if splitter_state is not None:
            self.splitter.restoreState(splitter_state)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/splitter", self.splitter.saveState())
        # QSettings flushes on its own schedule; the layout should already be
        # on disk when the window is gone.
        self.settings.sync()
        super().closeEvent(event)

    # ------------------------------------------------------------------ list

    def reload_connections(self) -> None:
        selected_id = self.selected_id()

        self.connections = self.service.list_connections(self.search.text().strip())

        self.connection_list.blockSignals(True)
        self.connection_list.clear()

        new_row = -1
        for row, connection in enumerate(self.connections):
            item = QListWidgetItem(connection.name)
            item.setData(Qt.ItemDataRole.UserRole, connection.id)

            subtitle = f"{connection.username}@{connection.hostname}:{connection.port}"
            item.setToolTip(subtitle)

            if connection.group_name:
                item.setText(f"{connection.name}\n  {connection.group_name}")

            self.connection_list.addItem(item)

            if connection.id == selected_id:
                new_row = row

        self.connection_list.blockSignals(False)

        if new_row >= 0:
            self.connection_list.setCurrentRow(new_row)
        elif self.connections:
            self.connection_list.setCurrentRow(0)
        else:
            self.clear_details()

        self.update_count_label()

    def update_count_label(self) -> None:
        count = len(self.connections)
        label = "1 connection" if count == 1 else f"{count} connections"
        if self.search.text().strip():
            total = len(self.service.list_connections())
            label += f" of {total}"
        self.count_label.setText(label)

    def schedule_reload(self, _text: str = "") -> None:
        self.search_timer.start()

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def selected_id(self) -> str | None:
        item = self.connection_list.currentItem()
        if not item:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def select_by_id(self, connection_id: str) -> None:
        """Select the row holding ``connection_id``, if it is currently listed."""
        for row in range(self.connection_list.count()):
            item = self.connection_list.item(row)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == connection_id:
                self.connection_list.setCurrentRow(row)
                return

    def selected_connection(self) -> Connection | None:
        connection_id = self.selected_id()
        if not connection_id:
            return None
        return self.service.get(connection_id)

    def selection_changed(
        self, current: QListWidgetItem | None, previous: QListWidgetItem | None
    ) -> None:
        del previous

        if current is None:
            self.clear_details()
            return

        connection = self.selected_connection()
        if connection is None:
            self.clear_details()
            return

        self.title_label.setText(connection.name)

        auth_labels = {
            "agent": "SSH Agent",
            "key": "Private Key",
            "password": "Password",
        }

        rows = (
            ("Host", connection.hostname),
            ("Port", connection.port),
            ("Username", connection.username),
            (
                "Authentication",
                auth_labels.get(connection.auth_method, connection.auth_method),
            ),
            ("Private key", connection.private_key or "None"),
            ("ProxyJump", connection.proxy_jump or "None"),
            ("Group", connection.group_name or "None"),
            ("UUID", connection.id),
        )
        # Notes and other fields are user input: escape them so they cannot be
        # interpreted as the markup of this rich-text label.
        table = "\n".join(
            f"<tr><td><b>{label}</b></td><td>{escape(str(value))}</td></tr>"
            for label, value in rows
        )
        notes = escape(connection.notes or "No notes.").replace("\n", "<br>")

        self.details_label.setText(
            f"""
            <table cellspacing="8">{table}</table>
            <br>
            <b>Notes</b><br>
            {notes}
            """
        )

        self.set_selection_actions_enabled(True)
        self.status.showMessage(f"Selected {connection.name}")

    def clear_details(self) -> None:
        self.title_label.setText("No connection selected")
        if self.search.text().strip():
            hint = "No connection matches your search."
        elif self.connections:
            hint = "Select a connection on the left."
        else:
            hint = "No connections yet — press Ctrl+N or use Add on the toolbar."
        self.details_label.setText(hint)
        self.set_selection_actions_enabled(False)

    def set_selection_actions_enabled(self, enabled: bool) -> None:
        for button in self.detail_buttons:
            button.setEnabled(enabled)
        for action in self.selection_actions:
            action.setEnabled(enabled)

    # ------------------------------------------------------------------ actions

    def add_connection(self) -> None:
        dialog = ConnectionDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        connection = self.service.create(**dialog.data())
        self.reload_connections()
        self.select_by_id(connection.id)
        self.status.showMessage("Connection created")

    def edit_selected(self) -> None:
        connection = self.selected_connection()
        if connection is None:
            return

        dialog = ConnectionDialog(self, connection)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self.service.update(connection.id, **dialog.data())
        self.reload_connections()
        self.select_by_id(connection.id)
        self.status.showMessage("Connection updated")

    def duplicate_selected(self) -> None:
        connection = self.selected_connection()
        if connection is None:
            return

        duplicate = self.service.duplicate(connection.id)
        if duplicate:
            self.reload_connections()
            self.select_by_id(duplicate.id)
            self.status.showMessage(f"Duplicated as “{duplicate.name}”")

    def delete_selected(self) -> None:
        connection = self.selected_connection()
        if connection is None:
            return

        answer = QMessageBox.question(
            self,
            "Delete connection",
            f'Delete "{connection.name}"?\n\nThis cannot be undone.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        self.service.delete(connection.id)
        self.reload_connections()
        self.status.showMessage("Connection deleted")

    def connect_selected(self) -> None:
        connection = self.selected_connection()
        if connection is None:
            return

        try:
            launched = self.service.connect(connection)
        except (TerminalError, OSError) as exc:
            QMessageBox.warning(self, "Could not open terminal", str(exc))
            return

        message = (
            f"Opened {launched.name} for {connection.username}@{connection.hostname}"
        )
        if launched.warnings:
            message += " — " + " ".join(launched.warnings)
        self.status.showMessage(message)

    def show_about(self) -> None:
        try:
            terminal = resolve_terminal().name
        except TerminalNotFoundError:
            terminal = "none found"

        QMessageBox.about(
            self,
            "About SSH Manager",
            f"""
            <h3>SSH Manager {__version__}</h3>
            <p>Manage SSH connections and open them in a terminal window.</p>
            <p>Sessions are run by the system <code>ssh</code> client; passwords
            and key contents are never stored.</p>
            <table>
              <tr><td><b>Qt</b></td><td>{qVersion()}</td></tr>
              <tr><td><b>Terminal</b></td><td>{escape(terminal)}</td></tr>
              <tr><td><b>Database</b></td>
                  <td><code>{escape(str(self.database.path))}</code>
                      (schema {self.database.schema_version()})</td></tr>
            </table>
            """,
        )

    # ------------------------------------------------------------------ import/export

    def import_ssh_config(self) -> None:
        default_path = Path.home() / ".ssh" / "config"
        start = str(default_path if default_path.exists() else Path.home() / ".ssh")
        path, _ = QFileDialog.getOpenFileName(self, "Import SSH config", start)
        if not path:
            return

        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            QMessageBox.warning(self, "Import failed", f"Could not read {path}:\n{exc}")
            return

        report = parse_ssh_config_report(text)
        if not report.hosts:
            message = "No importable hosts were found in this file."
            if report.warnings:
                message += "\n\n" + "\n".join(report.warnings)
            QMessageBox.information(self, "Import SSH config", message)
            return

        dialog = ImportPreviewDialog(
            report.hosts, self.service.existing_names(), report.warnings, self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        hosts = dialog.selected_hosts()
        if not hosts:
            QMessageBox.information(self, "Import SSH config", "No hosts were selected.")
            return

        summary = self.service.import_connections(hosts, dialog.selected_policy())
        self.reload_connections()

        parts = [f"{summary.imported} imported"]
        if summary.overwritten:
            parts.append(f"{summary.overwritten} overwritten")
        parts.append(f"{summary.skipped} skipped")
        message = ", ".join(parts) + "."
        if summary.warnings:
            message += "\n\n" + "\n".join(summary.warnings[:10])
            if len(summary.warnings) > 10:
                message += f"\n… and {len(summary.warnings) - 10} more."
        QMessageBox.information(self, "Import SSH config", message)
        self.status.showMessage(f"Imported {summary.imported} connection(s)")

    def export_ssh_config(self) -> None:
        connections = self.service.list_connections()
        if not connections:
            QMessageBox.information(
                self, "Export SSH config", "There are no connections to export."
            )
            return

        default_path = Path.home() / ".ssh" / "config.ssh-manager-export"
        path, _ = QFileDialog.getSaveFileName(self, "Export SSH config", str(default_path))
        if not path:
            return

        target = Path(path)
        if target.exists():
            answer = QMessageBox.question(
                self,
                "Overwrite file",
                f"{target} already exists.\n\nOverwrite it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        try:
            # Created with 0600 from the start; no window with looser
            # permissions. Then tighten files that already existed.
            with os.fdopen(
                os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(self.service.export_ssh_config())
            os.chmod(target, 0o600)
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", f"Could not write {target}:\n{exc}")
            return

        QMessageBox.information(
            self,
            "Export SSH config",
            f"Exported {len(connections)} connection(s) to {target}.",
        )
        self.status.showMessage(f"Exported {len(connections)} connection(s)")
