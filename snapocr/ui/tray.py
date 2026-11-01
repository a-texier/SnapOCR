"""Icone de barre systeme et menu. L'app vit ici, sans fenetre principale."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..paths import app_icon


def _load_icon() -> QIcon:
    path = app_icon()
    if path.exists():
        return QIcon(str(path))
    return QIcon()  # Qt fournit un fallback vide, remplace par le build.


class Tray(QSystemTrayIcon):
    capture_requested = Signal()
    settings_requested = Signal()
    quit_requested = Signal()

    def __init__(self, hotkey_label: str, parent=None):
        super().__init__(_load_icon(), parent)
        self._capture_action: QAction | None = None
        self.set_hotkey_label(hotkey_label)

        menu = QMenu()
        capture = QAction("Capturer", menu)
        capture.triggered.connect(self.capture_requested)
        menu.addAction(capture)
        self._capture_action = capture

        settings = QAction("Reglages...", menu)
        settings.triggered.connect(self.settings_requested)
        menu.addAction(settings)

        menu.addSeparator()

        quit_action = QAction("Quitter", menu)
        quit_action.triggered.connect(self.quit_requested)
        menu.addAction(quit_action)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def set_hotkey_label(self, hotkey_label: str) -> None:
        self.setToolTip(f"SnapOCR ({hotkey_label})")
        if self._capture_action is not None:
            self._capture_action.setText(f"Capturer  ({hotkey_label})")

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self.settings_requested.emit()
        elif reason == QSystemTrayIcon.Trigger:  # clic gauche simple
            self.capture_requested.emit()

    def notify(self, message: str) -> None:
        self.showMessage("SnapOCR", message)
