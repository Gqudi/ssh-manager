from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QStandardPaths
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from . import __version__
from .database.database import Database, SchemaTooNewError
from .ui.main_window import MainWindow

# Basename of the installed .desktop file, the icon, and the launcher.
DESKTOP_FILE_NAME = "ssh-manager"


def _app_icon() -> QIcon:
    """The installed theme icon, or the bundled SVG when run from a checkout."""
    icon = QIcon.fromTheme(DESKTOP_FILE_NAME)
    if not icon.isNull():
        return icon
    return QIcon(str(Path(__file__).parent / "assets" / f"{DESKTOP_FILE_NAME}.svg"))


def _data_directory() -> Path:
    """The platform's application-data directory, as Qt resolves it."""
    return Path(
        QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppLocalDataLocation
        )
    )


def main() -> None:
    # These names decide the application-data and settings directories: changing
    # them would strand databases of existing installations.
    QCoreApplication.setOrganizationName("SSH Manager")
    QCoreApplication.setOrganizationDomain("local")
    QCoreApplication.setApplicationName("SSH Manager")
    QCoreApplication.setApplicationVersion(__version__)

    app = QApplication(sys.argv)
    app.setApplicationDisplayName("SSH Manager")
    # Ties the window to ssh-manager.desktop so KDE (on Wayland especially)
    # shows the right icon in the taskbar and the menu entry.
    app.setDesktopFileName(DESKTOP_FILE_NAME)
    app.setWindowIcon(_app_icon())

    database = Database(_data_directory())
    try:
        database.initialize()
    except SchemaTooNewError as exc:
        QMessageBox.critical(None, "SSH Manager", str(exc))
        raise SystemExit(1) from exc

    window = MainWindow(database)
    window.show()

    sys.exit(app.exec())
