"""Enveloppe Tesseract : QImage -> mots avec boites (TSV image_to_data)."""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from .paths import tessdata_dir, tesseract_exe

CREATE_NO_WINDOW = 0x08000000


@dataclass
class Word:
    text: str
    left: int
    top: int
    width: int
    height: int
    line_key: tuple[int, int, int]  # (block, par, line) pour ordonner
    word_num: int
    conf: float


class OcrError(Exception):
    pass


def available() -> bool:
    return tesseract_exe().exists()


def _run(image_path: Path, lang: str) -> str:
    exe = tesseract_exe()
    if not exe.exists():
        raise OcrError(f"tesseract.exe introuvable: {exe}")
    cmd = [
        str(exe),
        str(image_path),
        "stdout",
        "-l",
        lang,
        "--tessdata-dir",
        str(tessdata_dir()),
        "--psm",
        "3",
        "tsv",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            creationflags=CREATE_NO_WINDOW,
        )
    except OSError as exc:
        raise OcrError(f"echec du lancement de tesseract: {exc}") from exc
    if proc.returncode != 0:
        raise OcrError(proc.stderr.strip() or "tesseract a echoue")
    return proc.stdout


# Au-dela de cette dimension (apres agrandissement) on plafonne : evite des images
# enormes et lentes sur les grandes captures, tout en zoomant fort les petites zones.
_MAX_SIDE = 3000


def recognize(
    image: QImage,
    lang: str = "eng+fra",
    min_conf: int = 30,
    upscale: float = 3.0,
) -> list[Word]:
    # Le texte d'ecran (UI Windows) est tres petit : Tesseract veut des lettres
    # d'environ 30-40 px. On agrandit donc l'image (interpolation lisse) avant OCR,
    # avec un facteur adaptatif plafonne, puis on ramene les boites a l'echelle
    # d'origine.
    scale = upscale if (upscale and upscale > 1 and not image.isNull()) else 1.0
    longest = max(image.width(), image.height())
    if longest * scale > _MAX_SIDE:
        scale = max(1.0, _MAX_SIDE / max(1, longest))
    ocr_image = image
    if scale != 1.0:
        ocr_image = image.scaled(
            max(1, int(image.width() * scale)),
            max(1, int(image.height() * scale)),
            Qt.IgnoreAspectRatio,
            Qt.SmoothTransformation,
        )

    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "capture.png"
        if not ocr_image.save(str(png), "PNG"):
            raise OcrError("impossible d'ecrire l'image temporaire")
        tsv = _run(png, lang)

    return _parse_tsv(tsv, scale, min_conf)


# Colonnes du TSV Tesseract, dans l'ordre. Le texte est toujours la derniere
# colonne et ne contient jamais de tabulation.
_TSV_COLS = (
    "level page_num block_num par_num line_num word_num "
    "left top width height conf text"
).split()
_COL = {name: i for i, name in enumerate(_TSV_COLS)}


def _parse_tsv(tsv: str, scale: float, min_conf: int) -> list[Word]:
    # Decoupage manuel sur les tabulations : on n'utilise PAS csv, dont le
    # guillemet par defaut fait fusionner les lignes des qu'un `"` parasite
    # apparait dans le texte OCR (ce qui arrive souvent) et fait perdre des mots.
    words: list[Word] = []
    lines = tsv.splitlines()
    for line in lines[1:]:  # saute l'entete
        parts = line.split("\t")
        if len(parts) <= _COL["text"]:
            continue
        if parts[_COL["level"]] != "5":  # 5 = mot
            continue
        text = parts[_COL["text"]].strip()
        if not text:
            continue
        try:
            conf = float(parts[_COL["conf"]])
            left = int(int(parts[_COL["left"]]) / scale)
            top = int(int(parts[_COL["top"]]) / scale)
            width = int(int(parts[_COL["width"]]) / scale)
            height = int(int(parts[_COL["height"]]) / scale)
            line_key = (
                int(parts[_COL["block_num"]]),
                int(parts[_COL["par_num"]]),
                int(parts[_COL["line_num"]]),
            )
            word_num = int(parts[_COL["word_num"]])
        except ValueError:
            continue
        if conf < min_conf:
            continue
        words.append(
            Word(
                text=text,
                left=left,
                top=top,
                width=width,
                height=height,
                line_key=line_key,
                word_num=word_num,
                conf=conf,
            )
        )
    return words


def full_text(words: list[Word]) -> str:
    """Reconstruit le texte dans l'ordre de lecture, un saut par ligne."""
    lines: list[tuple[tuple[int, int, int], list[Word]]] = []
    index: dict[tuple[int, int, int], list[Word]] = {}
    for w in words:
        if w.line_key not in index:
            bucket: list[Word] = []
            index[w.line_key] = bucket
            lines.append((w.line_key, bucket))
        index[w.line_key].append(w)
    out = []
    for _key, bucket in lines:
        bucket.sort(key=lambda w: w.word_num)
        out.append(" ".join(w.text for w in bucket))
    return "\n".join(out)
