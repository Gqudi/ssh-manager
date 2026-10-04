from __future__ import annotations

import sys

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from .database.database import Database
from .ui.main_window import MainWindow


def main() -> None:
    QCoreApplication.setOrganizationName("SSH Manager")
    QCoreApplication.setOrganizationDomain("local")
    QCoreApplication.setApplicationName("SSH Manager")

    app = QApplication(sys.argv)
    app.setApplicationDisplayName("SSH Manager")

    database = Database()
    database.create_tables()

    window = MainWindow(database)
    window.show()

    sys.exit(app.exec())
