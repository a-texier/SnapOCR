"""Lancement au demarrage via un raccourci dans le dossier Startup (sans admin)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_LNK_NAME = "SnapOCR.lnk"


def _startup_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA introuvable")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _lnk_path() -> Path:
    return _startup_dir() / _LNK_NAME


def _target() -> tuple[str, str]:
    """Retourne (cible, arguments) pour le raccourci.

    En bundle PyInstaller, sys.executable est le .exe de l'app.
    En dev, on relance python -m snapocr.
    """
    if getattr(sys, "frozen", False):
        return sys.executable, ""
    return sys.executable, "-m snapocr"


def is_enabled() -> bool:
    return _lnk_path().exists()


def enable() -> None:
    import win32com.client  # dependance pywin32, dispo dans IA_env

    target, args = _target()
    lnk = _lnk_path()
    lnk.parent.mkdir(parents=True, exist_ok=True)
    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortcut(str(lnk))
    shortcut.TargetPath = target
    if args:
        shortcut.Arguments = args
    shortcut.WorkingDirectory = str(Path(target).parent)
    shortcut.WindowStyle = 7  # minimise
    shortcut.save()


def disable() -> None:
    lnk = _lnk_path()
    if lnk.exists():
        lnk.unlink()


def set_enabled(value: bool) -> None:
    if value:
        enable()
    else:
        disable()
