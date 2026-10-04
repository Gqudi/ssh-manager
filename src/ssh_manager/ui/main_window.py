from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
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
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..database.database import Database
from ..database.models import Connection
from ..services.connection_service import ConnectionService
from ..services.ssh_config import parse_ssh_config_report
from ..services.terminal import TerminalError
from .connection_dialog import ConnectionDialog
from .import_dialog import ImportPreviewDialog


class MainWindow(QMainWindow):
    def __init__(self, database: Database) -> None:
        super().__init__()

        self.database = database
        self.service = ConnectionService(database)
        self.connections: list[Connection] = []

        self.setWindowTitle("SSH Manager")
        self.resize(1000, 650)
        self.setMinimumSize(800, 500)

        self.build_ui()
        self.build_actions()
        self.reload_connections()

    def build_ui(self) -> None:
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search connections…")
        self.search.textChanged.connect(self.reload_connections)

        self.connection_list = QListWidget()
        self.connection_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.connection_list.currentItemChanged.connect(self.selection_changed)
        self.connection_list.itemDoubleClicked.connect(lambda _: self.connect_selected())

        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.addWidget(self.search)
        sidebar_layout.addWidget(self.connection_list)

        self.empty_label = QLabel("Select a connection")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.details_frame = QFrame()
        details_layout = QVBoxLayout(self.details_frame)

        self.title_label = QLabel("No connection selected")
        self.title_label.setStyleSheet("font-size: 22px; font-weight: 600;")

        self.details_label = QLabel()
        self.details_label.setTextFormat(Qt.TextFormat.RichText)
        self.details_label.setWordWrap(True)

        button_row = QHBoxLayout()

        self.connect_button = QPushButton("Connect")
        self.edit_button = QPushButton("Edit")
        self.duplicate_button = QPushButton("Duplicate")
        self.delete_button = QPushButton("Delete")

        self.connect_button.clicked.connect(self.connect_selected)
        self.edit_button.clicked.connect(self.edit_selected)
        self.duplicate_button.clicked.connect(self.duplicate_selected)
        self.delete_button.clicked.connect(self.delete_selected)

        for button in (
            self.connect_button,
            self.edit_button,
            self.duplicate_button,
            self.delete_button,
        ):
            button_row.addWidget(button)

        button_row.addStretch()

        details_layout.addWidget(self.title_label)
        details_layout.addSpacing(12)
        details_layout.addWidget(self.details_label)
        details_layout.addStretch()
        details_layout.addLayout(button_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(sidebar)
        splitter.addWidget(self.details_frame)
        splitter.setSizes([300, 700])

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(splitter)

        self.setCentralWidget(central)

        self.status = QStatusBar()
        self.setStatusBar(self.status)

        self.set_detail_buttons_enabled(False)

    def build_actions(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        add_action = QAction("Add", self)
        add_action.triggered.connect(self.add_connection)

        import_action = QAction("Import…", self)
        import_action.setToolTip("Import connections from an SSH config file")
        import_action.setShortcut(QKeySequence("Ctrl+Shift+I"))
        import_action.triggered.connect(self.import_ssh_config)

        export_action = QAction("Export…", self)
        export_action.setToolTip("Export connections to an SSH config file")
        export_action.setShortcut(QKeySequence("Ctrl+Shift+E"))
        export_action.triggered.connect(self.export_ssh_config)

        toolbar.addAction(add_action)
        toolbar.addAction(import_action)
        toolbar.addAction(export_action)

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

    def selected_id(self) -> str | None:
        item = self.connection_list.currentItem()
        if not item:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def selected_connection(self) -> Connection | None:
        connection_id = self.selected_id()
        if not connection_id:
            return None
        return self.service.get(connection_id)

    def selection_changed(self, current, previous) -> None:
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

        group = connection.group_name or "None"
        key = connection.private_key or "None"

        self.details_label.setText(
            f"""
            <table cellspacing="8">
              <tr><td><b>Host</b></td><td>{connection.hostname}</td></tr>
              <tr><td><b>Port</b></td><td>{connection.port}</td></tr>
              <tr><td><b>Username</b></td><td>{connection.username}</td></tr>
              <tr><td><b>Authentication</b></td><td>{auth_labels.get(connection.auth_method, connection.auth_method)}</td></tr>
              <tr><td><b>Private key</b></td><td>{key}</td></tr>
              <tr><td><b>Group</b></td><td>{group}</td></tr>
              <tr><td><b>UUID</b></td><td><code>{connection.id}</code></td></tr>
            </table>
            <br>
            <b>Notes</b><br>
            {connection.notes or "No notes."}
            """
        )

        self.set_detail_buttons_enabled(True)
        self.status.showMessage(f"Selected {connection.name}")

    def clear_details(self) -> None:
        self.title_label.setText("No connection selected")
        self.details_label.clear()
        self.set_detail_buttons_enabled(False)

    def set_detail_buttons_enabled(self, enabled: bool) -> None:
        for button in (
            self.connect_button,
            self.edit_button,
            self.duplicate_button,
            self.delete_button,
        ):
            button.setEnabled(enabled)

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
            self.status.showMessage("Connection duplicated")

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
            self.service.connect(connection)
        except (TerminalError, OSError) as exc:
            QMessageBox.warning(self, "Could not open terminal", str(exc))
            return

        self.status.showMessage(
            f"Opening terminal for {connection.username}@{connection.hostname}"
        )

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
            return

        summary = self.service.import_connections(hosts)
        self.reload_connections()

        message = f"Imported {summary.imported}, skipped {summary.skipped}."
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
            target.write_text(self.service.export_ssh_config(), encoding="utf-8")
            try:
                os.chmod(target, 0o600)
            except OSError:
                pass
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", f"Could not write {target}:\n{exc}")
            return

        QMessageBox.information(
            self,
            "Export SSH config",
            f"Exported {len(connections)} connection(s) to {target}.",
        )
        self.status.showMessage(f"Exported {len(connections)} connection(s)")
