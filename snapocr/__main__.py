"""Point d'entree SnapOCR : app de fond (tray + raccourci global)."""
from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QMessageBox

from . import config as config_mod
from . import ocr
from .hotkey import HotkeyListener
from .ui.capture_overlay import CaptureOverlay
from .ui.settings_window import SettingsWindow
from .ui.tray import Tray

_FALLBACK_HOTKEY = "ctrl+shift+o"


def _set_dpi_aware() -> None:
    try:
        # Per-monitor v2 : overlay aligne sur les pixels physiques.
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass


class OcrWorker(QThread):
    done = Signal(object, list)  # (QImage, list[Word])
    failed = Signal(str)

    def __init__(self, image: QImage, lang: str, min_conf: int, upscale: float, parent=None):
        super().__init__(parent)
        self._image = image
        self._lang = lang
        self._min_conf = min_conf
        self._upscale = upscale

    def run(self) -> None:
        try:
            words = ocr.recognize(
                self._image, self._lang, self._min_conf, self._upscale
            )
        except ocr.OcrError as exc:
            self.failed.emit(str(exc))
            return
        self.done.emit(self._image, words)


class Controller(QObject):
    def __init__(self, app: QApplication):
        super().__init__()
        self._app = app
        self._cfg = config_mod.load()
        self._busy = False
        self._workers: list[OcrWorker] = []
        self._overlay: CaptureOverlay | None = None

        self._tray = Tray(self._cfg.hotkey)
        self._tray.capture_requested.connect(self.start_capture)
        self._tray.settings_requested.connect(self.open_settings)
        self._tray.quit_requested.connect(self._quit)
        self._tray.show()

        self._settings = SettingsWindow(self._cfg)
        self._settings.applied.connect(self._apply_settings)

        if not ocr.available():
            self._tray.notify(
                "tesseract.exe manquant dans resources/tesseract/. "
                "OCR indisponible tant qu'il n'est pas fourni."
            )

        self._listener: HotkeyListener | None = None
        self._start_hotkey(self._cfg.hotkey, allow_fallback=True)

    def _start_hotkey(self, spec: str, allow_fallback: bool) -> None:
        listener = HotkeyListener(spec)
        listener.triggered.connect(self.start_capture)

        def on_failed(msg: str) -> None:
            if allow_fallback and spec != _FALLBACK_HOTKEY:
                self._tray.notify(
                    f"Raccourci '{spec}' indisponible ({msg}). "
                    f"Bascule sur {_FALLBACK_HOTKEY}."
                )
                self._start_hotkey(_FALLBACK_HOTKEY, allow_fallback=False)
            else:
                self._tray.notify(f"Raccourci indisponible: {msg}")

        listener.failed.connect(on_failed)
        listener.start()
        self._listener = listener

    def open_settings(self) -> None:
        self._settings.load(self._cfg)
        self._settings.show()
        self._settings.raise_()
        self._settings.activateWindow()

    def _apply_settings(self, cfg) -> None:
        hotkey_changed = cfg.hotkey != self._cfg.hotkey
        self._cfg = cfg
        config_mod.save(cfg)
        self._tray.set_hotkey_label(cfg.hotkey)
        if hotkey_changed:
            if self._listener:
                self._listener.stop()
            self._start_hotkey(cfg.hotkey, allow_fallback=False)

    def start_capture(self) -> None:
        if self._busy:
            return
        if not ocr.available():
            self._tray.notify("tesseract.exe manquant : OCR impossible.")
            return
        self._busy = True
        overlay = CaptureOverlay()
        overlay.ocr_requested.connect(
            lambda img, rid, o=overlay: self._run_ocr(o, img, rid)
        )
        overlay.finished.connect(self._on_overlay_finished)
        self._overlay = overlay
        overlay.start()

    def _on_overlay_finished(self) -> None:
        self._busy = False
        self._overlay = None

    def _run_ocr(self, overlay: CaptureOverlay, image: QImage, region_id: int) -> None:
        worker = OcrWorker(
            image, self._cfg.lang, self._cfg.min_confidence, self._cfg.upscale
        )
        worker.done.connect(
            lambda _img, words, o=overlay, r=region_id: o.set_words(words, r)
        )

        def on_failed(msg: str, o=overlay, r=region_id) -> None:
            o.set_words([], r)  # stoppe le glow, affiche "aucun texte"
            self._tray.notify(f"OCR echoue: {msg}")

        worker.failed.connect(on_failed)
        worker.finished.connect(lambda wk=worker: self._workers.remove(wk))
        self._workers.append(worker)
        worker.start()

    def _quit(self) -> None:
        if self._listener:
            self._listener.stop()
        self._tray.hide()
        self._app.quit()


def main() -> int:
    _set_dpi_aware()
    app = QApplication(sys.argv)
    app.setApplicationName("SnapOCR")
    app.setQuitOnLastWindowClosed(False)  # ferme le resultat sans tuer l'app

    if not Tray.isSystemTrayAvailable():
        QMessageBox.critical(None, "SnapOCR", "Barre systeme indisponible.")
        return 1

    controller = Controller(app)  # garde la reference vivante
    app._controller = controller  # evite le GC
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
