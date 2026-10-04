from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..database.models import Connection
from ..services.terminal import SUPPORTED_TERMINALS, TerminalNotFoundError, resolve_terminal


class ConnectionDialog(QDialog):
    def __init__(self, parent=None, connection: Connection | None = None) -> None:
        super().__init__(parent)
        self.connection = connection
        self.setWindowTitle("Edit Connection" if connection else "Add Connection")
        self.setMinimumSize(560, 520)

        self.name_edit = QLineEdit()
        self.hostname_edit = QLineEdit()
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(22)
        self.username_edit = QLineEdit()

        self.auth_combo = QComboBox()
        self.auth_combo.addItem("SSH Agent", "agent")
        self.auth_combo.addItem("Private Key", "key")
        self.auth_combo.addItem("Password", "password")

        self.key_edit = QLineEdit()
        self.key_browse = QPushButton("Browse…")
        self.key_browse.clicked.connect(self.browse_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key_edit)
        key_row.addWidget(self.key_browse)

        self.group_edit = QLineEdit()
        self.notes_edit = QPlainTextEdit()

        basic = QWidget()
        basic_form = QFormLayout(basic)
        basic_form.addRow("Name *", self.name_edit)
        basic_form.addRow("Hostname *", self.hostname_edit)
        basic_form.addRow("Port", self.port_spin)
        basic_form.addRow("Username *", self.username_edit)
        basic_form.addRow("Authentication", self.auth_combo)
        basic_form.addRow("Private key", key_row)
        basic_form.addRow("Group", self.group_edit)
        basic_form.addRow("Notes", self.notes_edit)

        self.forward_agent = QCheckBox("Forward SSH agent (-A)")
        self.compression = QCheckBox("Compression (-C)")
        self.x11 = QCheckBox("X11 forwarding (-X)")
        self.keepalive = QSpinBox()
        self.keepalive.setRange(0, 3600)
        self.keepalive.setSuffix(" s")
        self.keepalive.setSpecialValueText("Disabled")

        self.proxy_jump = QLineEdit()
        self.proxy_jump.setPlaceholderText("jump-host or user@jump-host")

        self.remote_command = QLineEdit()
        self.remote_command.setPlaceholderText("Optional command, e.g. htop")

        self.extra_options = QPlainTextEdit()
        self.extra_options.setPlaceholderText("One OpenSSH -o option per line, e.g.\nStrictHostKeyChecking=accept-new")
        self.extra_options.setFixedHeight(100)

        ssh = QWidget()
        ssh_form = QFormLayout(ssh)
        ssh_form.addRow(self.forward_agent)
        ssh_form.addRow(self.compression)
        ssh_form.addRow(self.x11)
        ssh_form.addRow("KeepAlive", self.keepalive)
        ssh_form.addRow("ProxyJump", self.proxy_jump)
        ssh_form.addRow("Remote command", self.remote_command)
        ssh_form.addRow("Extra SSH options", self.extra_options)

        self.terminal_combo = QComboBox()
        system_label = "System default"
        try:
            detected = resolve_terminal()
        except TerminalNotFoundError:
            detected = None
        if detected is not None:
            system_label = f"System default ({detected.name})"
        self.terminal_combo.addItem(system_label, "system")
        for terminal in SUPPORTED_TERMINALS:
            self.terminal_combo.addItem(terminal, terminal)

        terminal_page = QWidget()
        terminal_form = QFormLayout(terminal_page)
        terminal_form.addRow("Terminal", self.terminal_combo)

        tabs = QTabWidget()
        tabs.addTab(basic, "Connection")
        tabs.addTab(ssh, "SSH Options")
        tabs.addTab(terminal_page, "Terminal")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

        self.auth_combo.currentIndexChanged.connect(self.update_key_state)
        self.load_connection()
        self.update_key_state()

    def load_connection(self) -> None:
        if not self.connection:
            return
        c = self.connection
        self.name_edit.setText(c.name)
        self.hostname_edit.setText(c.hostname)
        self.port_spin.setValue(c.port)
        self.username_edit.setText(c.username)
        idx = self.auth_combo.findData(c.auth_method)
        if idx >= 0:
            self.auth_combo.setCurrentIndex(idx)
        self.key_edit.setText(c.private_key or "")
        self.group_edit.setText(c.group_name or "")
        self.notes_edit.setPlainText(c.notes or "")
        self.forward_agent.setChecked(c.forward_agent)
        self.compression.setChecked(c.compression)
        self.x11.setChecked(c.x11_forwarding)
        self.keepalive.setValue(c.server_alive_interval)
        self.proxy_jump.setText(c.proxy_jump or "")
        self.remote_command.setText(c.remote_command or "")
        self.extra_options.setPlainText(c.extra_options or "")
        idx = self.terminal_combo.findData(c.terminal)
        if idx < 0 and c.terminal:
            # Keep custom terminal values that are not in the standard list.
            self.terminal_combo.addItem(c.terminal, c.terminal)
            idx = self.terminal_combo.findData(c.terminal)
        if idx >= 0:
            self.terminal_combo.setCurrentIndex(idx)

    def update_key_state(self) -> None:
        enabled = self.auth_combo.currentData() == "key"
        self.key_edit.setEnabled(enabled)
        self.key_browse.setEnabled(enabled)

    def browse_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select SSH private key", str(Path.home() / ".ssh"))
        if path:
            self.key_edit.setText(path)

    def validate_and_accept(self) -> None:
        if not self.name_edit.text().strip():
            self.name_edit.setFocus(); return
        if not self.hostname_edit.text().strip():
            self.hostname_edit.setFocus(); return
        if not self.username_edit.text().strip():
            self.username_edit.setFocus(); return
        if self.auth_combo.currentData() == "key" and not self.key_edit.text().strip():
            self.key_edit.setFocus(); return
        self.accept()

    def data(self) -> dict:
        return {
            "name": self.name_edit.text().strip(),
            "hostname": self.hostname_edit.text().strip(),
            "port": self.port_spin.value(),
            "username": self.username_edit.text().strip(),
            "auth_method": self.auth_combo.currentData(),
            "private_key": self.key_edit.text().strip() or None,
            "group_name": self.group_edit.text().strip() or None,
            "notes": self.notes_edit.toPlainText().strip() or None,
            "forward_agent": self.forward_agent.isChecked(),
            "compression": self.compression.isChecked(),
            "x11_forwarding": self.x11.isChecked(),
            "server_alive_interval": self.keepalive.value(),
            "proxy_jump": self.proxy_jump.text().strip() or None,
            "remote_command": self.remote_command.text().strip() or None,
            "extra_options": self.extra_options.toPlainText().strip() or None,
            "terminal": self.terminal_combo.currentData(),
        }
