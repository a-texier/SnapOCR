"""Raccourci global via RegisterHotKey natif Windows (sans admin).

Une fenetre message-only cachee recoit les WM_HOTKEY dans un thread dedie
et emet un signal Qt. La combinaison est configurable (ex: win+shift+o).
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QThread, Signal

user32 = ctypes.windll.user32

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

_MODIFIERS = {
    "alt": MOD_ALT,
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "super": MOD_WIN,
    "meta": MOD_WIN,
}

# Touches speciales -> virtual-key codes.
_SPECIAL_VK = {
    "space": 0x20,
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "esc": 0x1B,
    "escape": 0x1B,
}


class HotkeyError(Exception):
    pass


def parse(spec: str) -> tuple[int, int]:
    """'win+shift+o' -> (modifiers_flags, virtual_key)."""
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    if not parts:
        raise HotkeyError("raccourci vide")
    mods = 0
    key_vk: int | None = None
    for p in parts:
        if p in _MODIFIERS:
            mods |= _MODIFIERS[p]
        elif p in _SPECIAL_VK:
            key_vk = _SPECIAL_VK[p]
        elif len(p) == 1:
            key_vk = ord(p.upper())
        elif p.startswith("f") and p[1:].isdigit():
            key_vk = 0x70 + int(p[1:]) - 1  # F1 = 0x70
        else:
            raise HotkeyError(f"touche inconnue: {p}")
    if key_vk is None:
        raise HotkeyError("aucune touche principale dans le raccourci")
    return mods | MOD_NOREPEAT, key_vk


class HotkeyListener(QThread):
    """Thread qui enregistre le hotkey et emet triggered() a chaque appui."""

    triggered = Signal()
    failed = Signal(str)

    _HOTKEY_ID = 1

    def __init__(self, spec: str, parent=None):
        super().__init__(parent)
        self._spec = spec
        self._thread_id: int | None = None

    def run(self) -> None:
        try:
            mods, vk = parse(self._spec)
        except HotkeyError as exc:
            self.failed.emit(str(exc))
            return

        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, self._HOTKEY_ID, mods, vk):
            self.failed.emit(
                f"impossible d'enregistrer '{self._spec}' (deja utilise ?)"
            )
            return

        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == WM_HOTKEY:
                    self.triggered.emit()
        finally:
            user32.UnregisterHotKey(None, self._HOTKEY_ID)

    def stop(self) -> None:
        if self._thread_id is not None:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self.wait(2000)
