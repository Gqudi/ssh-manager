"""Conflict handling in the import preview dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt

from ssh_manager.services.connection_service import ConnectionService
from ssh_manager.services.ssh_config import ImportedHost
from ssh_manager.ui.import_dialog import POLICIES, ImportPreviewDialog


def host(name: str, hostname: str = "example.com") -> ImportedHost:
    return ImportedHost(name=name, hostname=hostname, username="user")


def test_new_hosts_are_checked_and_clashes_are_not(qapp) -> None:
    dialog = ImportPreviewDialog([host("Prod"), host("Fresh")], {"prod"})

    assert [entry.name for entry in dialog.selected_hosts()] == ["Fresh"]
    assert dialog.selected_policy() == "skip"
    assert dialog.table.item(0, 2).text().endswith("will be skipped")
    assert dialog.table.item(1, 2).text() == "New"


def test_overwrite_policy_selects_the_clash_and_says_so(qapp) -> None:
    dialog = ImportPreviewDialog([host("Prod")], {"prod"})

    dialog.policy_combo.setCurrentIndex(1)

    assert dialog.selected_policy() == "overwrite"
    assert [entry.name for entry in dialog.selected_hosts()] == ["Prod"]
    assert dialog.table.item(0, 2).text().endswith("will be overwritten")
    assert dialog.selection_label.text() == "1 of 1 selected."


def test_duplicate_policy_imports_the_clash_as_a_copy(qapp) -> None:
    dialog = ImportPreviewDialog([host("Prod")], {"prod"})

    dialog.policy_combo.setCurrentIndex(2)

    assert dialog.selected_policy() == "duplicate"
    assert [entry.name for entry in dialog.selected_hosts()] == ["Prod"]
    assert dialog.table.item(0, 2).text().endswith("as a copy")


def test_switching_back_to_skip_unchecks_the_clash(qapp) -> None:
    dialog = ImportPreviewDialog([host("Prod")], {"prod"})

    dialog.policy_combo.setCurrentIndex(1)
    dialog.policy_combo.setCurrentIndex(0)

    assert dialog.selected_hosts() == []


def test_policy_changes_leave_unrelated_rows_alone(qapp) -> None:
    dialog = ImportPreviewDialog([host("Prod"), host("Fresh")], {"prod"})
    fresh = dialog.table.item(1, 0)
    fresh.setCheckState(Qt.CheckState.Unchecked)  # the user opts this one out

    dialog.policy_combo.setCurrentIndex(1)  # overwrite

    assert fresh.checkState() == Qt.CheckState.Unchecked
    assert [entry.name for entry in dialog.selected_hosts()] == ["Prod"]


def test_the_service_accepts_every_policy_the_dialog_offers(
    qapp, service: ConnectionService
) -> None:
    for _label, value in POLICIES:
        summary = service.import_connections([], value)
        assert summary.imported == 0
