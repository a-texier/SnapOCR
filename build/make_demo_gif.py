"""Genere docs/demo.gif : l'overlay reel rendu hors ecran sur un faux bureau.

Aucune capture de l'ecran : le fond est dessine ici, l'OCR est le vrai Tesseract
embarque. Lancer depuis la racine : python build/make_demo_gif.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from snapocr import ocr  # noqa: E402
from snapocr.ui.capture_overlay import CaptureOverlay  # noqa: E402

W, H = 960, 540
OUT_WIDTH = 720
OUTPUT = ROOT / "docs" / "demo.gif"
DOC_TEXT = [
    "Rapport trimestriel",
    "Le chiffre d'affaires progresse de 12 % sur la periode,",
    "porte par les ventes en ligne et les nouveaux clients.",
    "Next steps: review the budget and ship version 2.0.",
]
ZONE = QRectF(150, 175, 600, 190)


def _window(p: QPainter, rect: QRectF, title: str) -> None:
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0, 40))
    p.drawRoundedRect(rect.translated(0, 4), 8, 8)
    p.setBrush(QColor(250, 250, 252))
    p.drawRoundedRect(rect, 8, 8)
    p.setBrush(QColor(232, 235, 240))
    p.drawRoundedRect(QRectF(rect.left(), rect.top(), rect.width(), 34), 8, 8)
    p.drawRect(QRectF(rect.left(), rect.top() + 20, rect.width(), 14))
    p.setPen(QColor(60, 64, 72))
    p.setFont(QFont("Segoe UI", 10))
    p.drawText(QRectF(rect.left() + 14, rect.top(), 400, 34), Qt.AlignVCenter, title)


def desktop(pasted: str | None = None) -> QPixmap:
    pix = QPixmap(W, H)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    grad_top, grad_bottom = QColor(38, 70, 120), QColor(90, 60, 130)
    for y in range(H):
        t = y / H
        p.setPen(QColor(
            int(grad_top.red() * (1 - t) + grad_bottom.red() * t),
            int(grad_top.green() * (1 - t) + grad_bottom.green() * t),
            int(grad_top.blue() * (1 - t) + grad_bottom.blue() * t),
        ))
        p.drawLine(0, y, W, y)

    _window(p, QRectF(120, 110, 660, 290), "rapport.pdf")
    p.setPen(QColor(25, 28, 34))
    p.setFont(QFont("Segoe UI", 20, QFont.Bold))
    p.drawText(QPointF(170, 210), DOC_TEXT[0])
    p.setFont(QFont("Segoe UI", 15))
    for i, line in enumerate(DOC_TEXT[1:]):
        p.drawText(QPointF(170, 260 + i * 36), line)

    if pasted is not None:
        note = QRectF(410, 320, 530, 180)
        _window(p, note, "Bloc-notes")
        p.setPen(QColor(25, 28, 34))
        p.setFont(QFont("Consolas", 11))
        p.drawText(note.adjusted(14, 46, -14, -10), Qt.TextWordWrap, pasted)
    p.end()
    return pix


def with_cursor(img: QImage, pos: QPointF | None) -> QImage:
    if pos is None:
        return img
    img = img.copy()
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath(pos)
    for dx, dy in ((0, 18), (4.5, 14), (8, 21), (11, 19.5), (7.5, 13), (13, 13)):
        path.lineTo(pos.x() + dx, pos.y() + dy)
    path.closeSubpath()
    p.setPen(QPen(QColor(0, 0, 0), 1.2))
    p.setBrush(QColor(255, 255, 255))
    p.drawPath(path)
    p.end()
    return img


def toast(img: QImage, text: str) -> QImage:
    img = img.copy()
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    box = QRectF(W - 250, 24, 226, 44)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(20, 24, 34, 235))
    p.drawRoundedRect(box, 8, 8)
    p.setPen(QColor(230, 236, 245))
    p.setFont(QFont("Segoe UI", 11))
    p.drawText(box, Qt.AlignCenter, text)
    p.end()
    return img


def to_pil(img: QImage) -> Image.Image:
    img = img.convertToFormat(QImage.Format_RGB888)
    data = bytes(img.constBits())[: img.bytesPerLine() * img.height()]
    frame = Image.frombuffer("RGB", (img.width(), img.height()), data, "raw", "RGB",
                             img.bytesPerLine(), 1)
    return frame.resize((OUT_WIDTH, int(H * OUT_WIDTH / W)), Image.LANCZOS)


def lerp(a: QPointF, b: QPointF, t: float) -> QPointF:
    return QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t)


def main() -> int:
    app = QApplication(sys.argv)
    if not ocr.available():
        print("tesseract.exe manquant : lance build/fetch_assets.ps1", file=sys.stderr)
        return 1
    frames: list[tuple[Image.Image, int]] = []

    def add(img: QImage, ms: int, cursor: QPointF | None = None) -> None:
        frames.append((to_pil(with_cursor(img, cursor)), ms))

    base = desktop()
    start, end = ZONE.topLeft(), ZONE.bottomRight()
    add(base.toImage(), 900, QPointF(480, 450))
    add(toast(base.toImage(), "Win + Shift + O"), 900, QPointF(480, 450))

    overlay = CaptureOverlay()
    overlay._pix = base
    overlay._dpr = 1.0
    overlay.resize(W, H)
    overlay._panel.show_hint("Glissez pour selectionner une zone de texte")
    overlay._place_panel()
    crops: list[QImage] = []
    overlay.ocr_requested.connect(lambda img, _rid: crops.append(img))
    add(overlay.grab().toImage(), 700, start)

    for i in range(1, 11):
        overlay._rect = QRectF(start, lerp(start, end, i / 10)).normalized()
        overlay.update()
        add(overlay.grab().toImage(), 70, lerp(start, end, i / 10))

    overlay._request_ocr()
    overlay._glow.stop()
    words = ocr.recognize(crops[-1], "eng+fra", 30, 3.0)
    for _ in range(10):
        overlay._angle = (overlay._angle + 24) % 360
        add(overlay.grab().toImage(), 60, end)

    overlay.set_words(words, overlay._region_id)
    add(overlay.grab().toImage(), 900, end)

    # Selection a la souris de la deuxieme phrase, mot a mot.
    line_keys = sorted({w.line_key for w in words})
    first = next(i for i, w in enumerate(words) if w.line_key == line_keys[1])
    last = max(i for i, w in enumerate(words) if w.line_key == line_keys[2])
    rects = [r for _, r in overlay._words]
    overlay._start_text_selection(rects[first].center(), Qt.NoModifier)
    for idx in range(first, last + 1):
        overlay._sel = overlay._range(first, idx)
        overlay.update()
        add(overlay.grab().toImage(), 90, rects[idx].center())
    add(overlay.grab().toImage(), 900, rects[last].center())
    add(toast(overlay.grab().toImage(), "Ctrl + C"), 800, rects[last].center())

    pasted = ocr.full_text([words[i] for i in range(first, last + 1)])
    final = toast(desktop(pasted).toImage(), "Texte copie")
    add(final, 3000, QPointF(700, 470))

    images = [f for f, _ in frames]
    OUTPUT.parent.mkdir(exist_ok=True)
    images[0].save(
        OUTPUT,
        save_all=True,
        append_images=images[1:],
        duration=[ms for _, ms in frames],
        loop=0,
        optimize=True,
    )
    print(f"{OUTPUT.relative_to(ROOT)} : {len(images)} images, "
          f"{OUTPUT.stat().st_size / 1024:.0f} Ko, texte colle : {pasted!r}")
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
