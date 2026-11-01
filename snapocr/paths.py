"""Resolution des chemins, compatible mode dev et bundle PyInstaller."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def resource_path(*parts: str) -> Path:
    """Chemin vers une ressource embarquee (resources/...).

    En bundle PyInstaller les donnees sont extraites dans sys._MEIPASS ;
    en dev elles sont a cote du package.
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        root = Path(base)
    else:
        root = Path(__file__).resolve().parent
    return root.joinpath(*parts)


def tesseract_dir() -> Path:
    return resource_path("resources", "tesseract")


def tesseract_exe() -> Path:
    return tesseract_dir() / "tesseract.exe"


def tessdata_dir() -> Path:
    return tesseract_dir() / "tessdata"


def config_dir() -> Path:
    """Dossier de config par utilisateur (portable-friendly, pas d'admin)."""
    base = os.environ.get("APPDATA") or str(Path.home())
    d = Path(base) / "SnapOCR"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return config_dir() / "config.json"


def app_icon() -> Path:
    return resource_path("resources", "icon.png")
