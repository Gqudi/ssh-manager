from __future__ import annotations

from collections.abc import Iterable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..services.ssh_config import ImportedHost


class ImportPreviewDialog(QDialog):
    """Lets the user pick which parsed hosts to import."""

    def __init__(
        self,
        hosts: Iterable[ImportedHost],
        existing_names: set[str],
        warnings: Sequence[str] = (),
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import SSH config")
        self.resize(640, 480)

        self._hosts = list(hosts)

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

            exists = host.name.lower() in existing_names

            alias_item = QTableWidgetItem(host.name)
            alias_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            alias_item.setCheckState(
                Qt.CheckState.Unchecked if exists else Qt.CheckState.Checked
            )
            self.table.setItem(row, 0, alias_item)

            self.table.setItem(
                row, 1, QTableWidgetItem(f"{host.username}@{host.hostname}:{host.port}")
            )
            status = "Already exists — will be skipped" if exists else "New"
            self.table.setItem(row, 2, QTableWidgetItem(status))

        layout = QVBoxLayout(self)
        if warnings:
            note = QLabel(
                f"{len(warnings)} other entry/entries in the file were skipped "
                "(wildcards, Match or Include blocks). Hover for details."
            )
            note.setToolTip("\n".join(warnings))
            layout.addWidget(note)
        layout.addWidget(self.table)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Import")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_hosts(self) -> list[ImportedHost]:
        return [
            host
            for row, host in enumerate(self._hosts)
            if self.table.item(row, 0).checkState() == Qt.CheckState.Checked
        ]
