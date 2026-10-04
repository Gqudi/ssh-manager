from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .database.database import Database
from .ui.main_window import MainWindow

# Basename of the installed .desktop file, the icon, and the launcher.
DESKTOP_FILE_NAME = "ssh-manager"


def _app_icon() -> QIcon:
    """The installed theme icon, or the bundled SVG when run from a checkout."""
    icon = QIcon.fromTheme(DESKTOP_FILE_NAME)
    if not icon.isNull():
        return icon
    return QIcon(str(Path(__file__).parent / "assets" / f"{DESKTOP_FILE_NAME}.svg"))


def main() -> None:
    QCoreApplication.setOrganizationName("SSH Manager")
    QCoreApplication.setOrganizationDomain("local")
    QCoreApplication.setApplicationName("SSH Manager")

    app = QApplication(sys.argv)
    app.setApplicationDisplayName("SSH Manager")
    # Ties the window to ssh-manager.desktop so KDE (on Wayland especially)
    # shows the right icon in the taskbar and the menu entry.
    app.setDesktopFileName(DESKTOP_FILE_NAME)
    app.setWindowIcon(_app_icon())

    database = Database()
    database.create_tables()

    window = MainWindow(database)
    window.show()

    sys.exit(app.exec())
