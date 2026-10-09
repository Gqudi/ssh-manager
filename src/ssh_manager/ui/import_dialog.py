from __future__ import annotations

from collections.abc import Iterable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..services.ssh_config import ImportedHost

#: Conflict policies in combo-box order: (label, value passed to the service).
POLICIES: tuple[tuple[str, str], ...] = (
    ("Skip them, keep the existing connection", "skip"),
    ("Overwrite the existing connection", "overwrite"),
    ("Import as a separate copy", "duplicate"),
)

_STATUS_TEXT = {
    "skip": "Already exists — will be skipped",
    "overwrite": "Already exists — will be overwritten",
    "duplicate": "Already exists — will be imported as a copy",
}


class ImportPreviewDialog(QDialog):
    """Lets the user pick which parsed hosts to import and how to handle clashes."""

    def __init__(
        self,
        hosts: Iterable[ImportedHost],
        existing_names: set[str],
        warnings: Sequence[str] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import SSH config")
        self.resize(720, 520)

        self._hosts = list(hosts)
        self._existing_names = existing_names

        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(["Alias", "Connection", "Status"])
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        for host in self._hosts:
            row = self.table.rowCount()
            self.table.insertRow(row)

            alias_item = QTableWidgetItem(host.name)
            alias_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            alias_item.setCheckState(self._initial_check_state(host))
            self.table.setItem(row, 0, alias_item)

            self.table.setItem(
                row, 1, QTableWidgetItem(f"{host.username}@{host.hostname}:{host.port}")
            )
            self.table.setItem(row, 2, QTableWidgetItem(self._status_text(host, "skip")))

        layout = QVBoxLayout(self)
        if warnings:
            note = QLabel(
                f"{len(warnings)} other entry/entries in the file were skipped "
                "(wildcards, Match or Include blocks). Hover for details."
            )
            note.setToolTip("\n".join(warnings))
            layout.addWidget(note)
        layout.addWidget(self.table)

        policy_row = QHBoxLayout()
        policy_row.addWidget(QLabel("If a connection with the same name exists:"))
        self.policy_combo = QComboBox()
        for label, value in POLICIES:
            self.policy_combo.addItem(label, value)
        policy_row.addWidget(self.policy_combo, 1)
        layout.addLayout(policy_row)

        self.selection_label = QLabel()
        layout.addWidget(self.selection_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Import")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Connected after populating, so filling the table does not fire them.
        self.table.itemChanged.connect(self.update_selection_label)
        self.policy_combo.currentIndexChanged.connect(self.apply_policy)
        self.update_selection_label()

    def _is_existing(self, host: ImportedHost) -> bool:
        return host.name.lower() in self._existing_names

    def _initial_check_state(self, host: ImportedHost) -> Qt.CheckState:
        # Clashes start unchecked: the default policy is to keep what is stored.
        return Qt.CheckState.Unchecked if self._is_existing(host) else Qt.CheckState.Checked

    def _status_text(self, host: ImportedHost, policy: str) -> str:
        if self._is_existing(host):
            return _STATUS_TEXT[policy]
        return "New"

    def apply_policy(self) -> None:
        """Check (or uncheck) clashing hosts to match the chosen policy."""
        policy = self.selected_policy()
        for row, host in enumerate(self._hosts):
            if not self._is_existing(host):
                continue
            item = self.table.item(row, 0)
            if item is not None:
                item.setCheckState(
                    Qt.CheckState.Checked
                    if policy in {"overwrite", "duplicate"}
                    else Qt.CheckState.Unchecked
                )
            status = self.table.item(row, 2)
            if status is not None:
                status.setText(self._status_text(host, policy))
        self.update_selection_label()

    def update_selection_label(self) -> None:
        self.selection_label.setText(
            f"{len(self.selected_hosts())} of {len(self._hosts)} selected."
        )

    def selected_policy(self) -> str:
        return self.policy_combo.currentData()

    def selected_hosts(self) -> list[ImportedHost]:
        hosts = []
        for row, host in enumerate(self._hosts):
            item = self.table.item(row, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                hosts.append(host)
        return hosts
