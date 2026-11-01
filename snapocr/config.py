"""Lecture/ecriture de la config JSON (raccourci, langues)."""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict

from .paths import config_path

DEFAULTS = {
    # Raccourci global. Modificateurs possibles: win, ctrl, alt, shift.
    "hotkey": "win+shift+o",
    # Langues Tesseract combinees.
    "lang": "eng+fra",
    # Confiance minimale (0-100) pour garder un mot.
    "min_confidence": 30,
    # Agrandissement de l'image avant OCR (petit texte UI : 3 recommande, 4 possible).
    "upscale": 3,
}


@dataclass
class Config:
    hotkey: str = DEFAULTS["hotkey"]
    lang: str = DEFAULTS["lang"]
    min_confidence: int = DEFAULTS["min_confidence"]
    upscale: int = DEFAULTS["upscale"]


def load() -> Config:
    path = config_path()
    if not path.exists():
        cfg = Config()
        save(cfg)
        return cfg
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return Config()
    merged = {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}
    return Config(**merged)


def save(cfg: Config) -> None:
    config_path().write_text(
        json.dumps(asdict(cfg), indent=2, ensure_ascii=False), encoding="utf-8"
    )
