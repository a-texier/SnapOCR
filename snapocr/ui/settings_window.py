"""Petite fenetre de reglages. La fermer la cache : l'app reste en fond (tray)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import startup
from ..config import Config
from ..hotkey import HotkeyError, parse
from ..paths import app_icon

_MODS = [("win", "Win"), ("ctrl", "Ctrl"), ("alt", "Alt"), ("shift", "Shift")]
_LANGS = [("eng+fra", "Anglais + Francais"), ("fra", "Francais"), ("eng", "Anglais")]


def _split_hotkey(spec: str) -> tuple[set[str], str]:
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    mods = {p for p in parts if p in {m for m, _ in _MODS}}
    key = next((p for p in parts if p not in mods), "")
    return mods, key


class SettingsWindow(QWidget):
    # Emise a chaque application : (nouvelle config). Le controleur applique.
    applied = Signal(object)

    def __init__(self, cfg: Config):
        super().__init__()
        self.setWindowTitle("SnapOCR - Reglages")
        icon = app_icon()
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        # --- Raccourci ---
        hk_box = QGroupBox("Raccourci de capture")
        self._mod_checks: dict[str, QCheckBox] = {}
        mods_row = QHBoxLayout()
        for key, label in _MODS:
            cb = QCheckBox(label)
            self._mod_checks[key] = cb
            cb.toggled.connect(self._update_preview)
            mods_row.addWidget(cb)
        mods_row.addStretch(1)

        self._key_edit = QLineEdit()
        self._key_edit.setMaxLength(3)
        self._key_edit.setFixedWidth(60)
        self._key_edit.setPlaceholderText("O")
        self._key_edit.textChanged.connect(self._update_preview)

        self._preview = QLabel()
        self._preview.setStyleSheet("color: palette(mid);")

        hk_form = QFormLayout()
        hk_form.addRow("Modificateurs", mods_row)
        hk_form.addRow("Touche", self._key_edit)
        hk_form.addRow("Apercu", self._preview)
        hk_box.setLayout(hk_form)

        # --- OCR ---
        ocr_box = QGroupBox("OCR")
        self._lang = QComboBox()
        for value, label in _LANGS:
            self._lang.addItem(label, value)
        self._conf = QSpinBox()
        self._conf.setRange(0, 100)
        self._conf.setSuffix(" %")
        self._upscale = QSpinBox()
        self._upscale.setRange(1, 4)
        self._upscale.setSuffix(" x")
        self._upscale.setToolTip(
            "Agrandit l'image avant l'OCR. Petit texte d'ecran : 3 recommande, "
            "4 pour du tres petit texte (plus lent)."
        )
        ocr_form = QFormLayout()
        ocr_form.addRow("Langues", self._lang)
        ocr_form.addRow("Confiance mini", self._conf)
        ocr_form.addRow("Agrandissement", self._upscale)
        ocr_box.setLayout(ocr_form)

        # --- Demarrage ---
        self._startup = QCheckBox("Lancer au demarrage de Windows")

        # --- Boutons ---
        self._status = QLabel("")
        apply_btn = QPushButton("Appliquer")
        close_btn = QPushButton("Fermer")
        apply_btn.clicked.connect(self._apply)
        close_btn.clicked.connect(self.close)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self._status, 1)
        btn_row.addWidget(apply_btn)
        btn_row.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(hk_box)
        layout.addWidget(ocr_box)
        layout.addWidget(self._startup)
        layout.addLayout(btn_row)
        layout.addStretch(1)

        self.setMinimumWidth(360)
        self.load(cfg)

    def load(self, cfg: Config) -> None:
        """Recharge les champs depuis la config (et l'etat demarrage reel)."""
        mods, key = _split_hotkey(cfg.hotkey)
        for name, cb in self._mod_checks.items():
            cb.setChecked(name in mods)
        self._key_edit.setText(key.upper())
        idx = self._lang.findData(cfg.lang)
        self._lang.setCurrentIndex(idx if idx >= 0 else 0)
        self._conf.setValue(cfg.min_confidence)
        self._upscale.setValue(cfg.upscale)
        self._startup.setChecked(startup.is_enabled())
        self._status.clear()
        self._update_preview()

    def _current_spec(self) -> str:
        parts = [name for name, _ in _MODS if self._mod_checks[name].isChecked()]
        key = self._key_edit.text().strip().lower()
        if key:
            parts.append(key)
        return "+".join(parts)

    def _update_preview(self) -> None:
        spec = self._current_spec()
        try:
            parse(spec)
            self._preview.setText(spec.replace("+", " + ").title() or "(vide)")
            self._preview.setStyleSheet("color: palette(mid);")
        except HotkeyError as exc:
            self._preview.setText(f"invalide: {exc}")
            self._preview.setStyleSheet("color: #d33;")

    def _apply(self) -> None:
        spec = self._current_spec()
        try:
            parse(spec)
        except HotkeyError as exc:
            self._status.setText(f"Raccourci invalide: {exc}")
            return
        cfg = Config(
            hotkey=spec,
            lang=self._lang.currentData(),
            min_confidence=self._conf.value(),
            upscale=self._upscale.value(),
        )
        try:
            startup.set_enabled(self._startup.isChecked())
        except Exception as exc:  # noqa: BLE001 - remonter proprement a l'UI
            self._status.setText(f"Demarrage: echec ({exc})")
            self._startup.setChecked(startup.is_enabled())
        self.applied.emit(cfg)
        self._status.setText("Applique.")

    def closeEvent(self, event) -> None:
        # Ne quitte pas l'app : on cache juste la fenetre.
        event.ignore()
        self.hide()
