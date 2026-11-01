"""Overlay plein ecran unique, facon Snip & Sketch + Google Lens.

Ecran assombri + panel en haut, on glisse pour tracer une zone : le vrai contenu
reste visible dans le rectangle, l'OCR s'y superpose (texte selectionnable en
place). Le rectangle est redimensionnable par ses poignees ; pendant le recalcul
un anneau multicolore brille autour. La copie ferme l'overlay, Echap aussi.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QCursor,
    QGuiApplication,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import QPushButton, QWidget

from ..ocr import Word, full_text

# Poignees de redimensionnement : TL, T, TR, R, BR, B, BL, L
_HANDLE_HIT = 12.0
_MIN_SIZE = 8.0
_CURSORS = [
    Qt.SizeFDiagCursor, Qt.SizeVerCursor, Qt.SizeBDiagCursor, Qt.SizeHorCursor,
    Qt.SizeFDiagCursor, Qt.SizeVerCursor, Qt.SizeBDiagCursor, Qt.SizeHorCursor,
]

_SEL_FILL = QColor(0, 170, 255, 80)
_SEL_LINE = QColor(0, 190, 255)
_GLOW_STOPS = [
    (0.00, QColor(0, 170, 255)),
    (0.25, QColor(150, 60, 255)),
    (0.50, QColor(255, 60, 150)),
    (0.75, QColor(80, 220, 120)),
    (1.00, QColor(0, 170, 255)),
]


class CaptureOverlay(QWidget):
    # (image du crop, id de region) : le controleur lance l'OCR et rappelle set_words.
    ocr_requested = Signal(QImage, int)
    finished = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        self._pix: QPixmap | None = None
        self._dpr = 1.0
        self._rect: QRectF | None = None
        self._state = "select"  # select | busy | ready

        # interaction souris
        self._mode: str | None = None  # new | resize | textsel
        self._handle = -1
        self._press: QPointF | None = None
        self._sel_rect: QRectF | None = None

        # OCR
        self._region_id = 0
        self._words: list[tuple[Word, QRectF]] = []  # (word, rect logique), ordre lecture
        self._lines: list[tuple[float, float, list[int]]] = []  # (top, bottom, indices)
        # selection type texte : plage contigue [ancre..focus], additive avec Ctrl
        self._sel: set[int] = set()
        self._anchor: int | None = None
        self._base_sel: set[int] = set()  # selection conservee pendant un ajout Ctrl

        # glow
        self._angle = 0
        self._glow = QTimer(self)
        self._glow.setInterval(33)
        self._glow.timeout.connect(self._tick)

        self._panel = _TopPanel(self)
        self._panel.copy_all.connect(self._copy_all)
        self._panel.copy_sel.connect(self._copy_selection)
        self._panel.select_all.connect(self._select_all)
        self._panel.retry.connect(self._new_selection)
        self._panel.close_req.connect(self._cancel)

        QShortcut(QKeySequence(Qt.Key_Escape), self, self._cancel)
        QShortcut(QKeySequence.Copy, self, self._copy_smart)
        QShortcut(QKeySequence.SelectAll, self, self._select_all)
        QShortcut(QKeySequence(Qt.Key_Return), self, self._copy_all)
        QShortcut(QKeySequence(Qt.Key_Enter), self, self._copy_all)

    # --- cycle de vie ---

    def start(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        self._dpr = screen.devicePixelRatio()
        pix = screen.grabWindow(0)
        pix.setDevicePixelRatio(1.0)
        self._pix = pix
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CrossCursor)
        self.showFullScreen()
        self.activateWindow()
        self.raise_()
        self.setFocus()
        self._panel.show_hint("Glissez pour selectionner une zone de texte")
        self._place_panel()

    def _cancel(self) -> None:
        self._glow.stop()
        self.finished.emit()
        self.close()

    # --- OCR ---

    def _request_ocr(self) -> None:
        if self._rect is None or self._pix is None:
            return
        r = self._rect.normalized()
        if r.width() < _MIN_SIZE or r.height() < _MIN_SIZE:
            self._cancel()
            return
        self._state = "busy"
        self._sel.clear()
        self._anchor = None
        self._words = []
        self._lines = []
        self._region_id += 1
        self._glow.start()
        self._panel.set_busy(True)
        self.update()
        src = self._physical_rect(r)
        crop = self._pix.copy(src).toImage()
        self.ocr_requested.emit(crop, self._region_id)

    def set_words(self, words: list[Word], region_id: int) -> None:
        if region_id != self._region_id or self._rect is None:
            return
        self._glow.stop()
        self._state = "ready"
        r = self._rect.normalized()
        self._words = []
        for w in words:
            wr = QRectF(
                r.left() + w.left / self._dpr,
                r.top() + w.top / self._dpr,
                w.width / self._dpr,
                w.height / self._dpr,
            )
            self._words.append((w, wr))
        self._build_lines()
        self._sel.clear()
        self._anchor = None
        self._panel.set_busy(False)
        self._panel.set_ready(len(words))
        self.setCursor(Qt.ArrowCursor)
        self.update()

    # --- selection type texte ---

    def _build_lines(self) -> None:
        """Regroupe les mots (dans l'ordre de lecture) par ligne visuelle."""
        self._lines = []
        current: list[int] = []
        cur_key = None
        for i, (w, wr) in enumerate(self._words):
            key = w.line_key
            if cur_key is not None and key != cur_key and current:
                self._flush_line(current)
                current = []
            cur_key = key
            current.append(i)
        if current:
            self._flush_line(current)

    def _flush_line(self, idxs: list[int]) -> None:
        top = min(self._words[i][1].top() for i in idxs)
        bottom = max(self._words[i][1].bottom() for i in idxs)
        idxs_sorted = sorted(idxs, key=lambda i: self._words[i][1].left())
        self._lines.append((top, bottom, idxs_sorted))

    def _caret_index(self, pos: QPointF) -> int | None:
        """Indice du mot le plus proche du point, facon curseur de texte."""
        if not self._lines:
            return None
        # ligne : celle contenant y, sinon la plus proche verticalement
        line = None
        for ln in self._lines:
            if ln[0] <= pos.y() <= ln[1]:
                line = ln
                break
        if line is None:
            line = min(self._lines, key=lambda ln: abs((ln[0] + ln[1]) / 2 - pos.y()))
        idxs = line[2]
        # mot : celui contenant x, sinon bord le plus proche
        for i in idxs:
            wr = self._words[i][1]
            if wr.left() <= pos.x() <= wr.right():
                return i
        if pos.x() <= self._words[idxs[0]][1].left():
            return idxs[0]
        if pos.x() >= self._words[idxs[-1]][1].right():
            return idxs[-1]
        return min(idxs, key=lambda i: abs(self._words[i][1].center().x() - pos.x()))

    def _range(self, a: int, b: int) -> set[int]:
        return set(range(min(a, b), max(a, b) + 1))

    # --- geometrie ---

    def _physical_rect(self, r: QRectF) -> QRect:
        return QRect(
            int(r.left() * self._dpr),
            int(r.top() * self._dpr),
            int(r.width() * self._dpr),
            int(r.height() * self._dpr),
        )

    def _handles(self, r: QRectF) -> list[QPointF]:
        l, t, rr, b = r.left(), r.top(), r.right(), r.bottom()
        cx, cy = (l + rr) / 2, (t + b) / 2
        return [
            QPointF(l, t), QPointF(cx, t), QPointF(rr, t), QPointF(rr, cy),
            QPointF(rr, b), QPointF(cx, b), QPointF(l, b), QPointF(l, cy),
        ]

    def _handle_at(self, pos: QPointF) -> int:
        if self._rect is None:
            return -1
        for i, h in enumerate(self._handles(self._rect.normalized())):
            if (abs(pos.x() - h.x()) <= _HANDLE_HIT
                    and abs(pos.y() - h.y()) <= _HANDLE_HIT):
                return i
        return -1

    def _resize_to(self, pos: QPointF) -> None:
        r = self._rect.normalized()
        l, t, rr, b = r.left(), r.top(), r.right(), r.bottom()
        i = self._handle
        if i in (0, 6, 7):
            l = pos.x()
        if i in (2, 3, 4):
            rr = pos.x()
        if i in (0, 1, 2):
            t = pos.y()
        if i in (4, 5, 6):
            b = pos.y()
        self._rect = QRectF(QPointF(l, t), QPointF(rr, b)).normalized()
        self._clamp_rect()

    def _clamp_rect(self) -> None:
        area = QRectF(self.rect())
        self._rect = self._rect.intersected(area)

    # --- souris ---

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        pos = event.position()
        if self._state == "ready":
            h = self._handle_at(pos)
            if h >= 0:
                self._mode = "resize"
                self._handle = h
                return
            if self._rect and self._rect.normalized().contains(pos):
                self._start_text_selection(pos, event.modifiers())
                return
        # sinon : nouvelle selection de zone
        self._mode = "new"
        self._press = pos
        self._rect = QRectF(pos, pos)
        self._state = "select"
        self.setCursor(Qt.CrossCursor)
        self.update()

    def _start_text_selection(self, pos: QPointF, mods) -> None:
        idx = self._caret_index(pos)
        if idx is None:
            self._mode = None
            return
        self._mode = "textsel"
        if mods & Qt.ShiftModifier and self._anchor is not None:
            # etendre la plage depuis l'ancre existante
            self._base_sel = set()
            self._sel = self._range(self._anchor, idx)
        elif mods & Qt.ControlModifier:
            # ajouter une nouvelle zone en gardant l'existante
            self._base_sel = set(self._sel)
            self._anchor = idx
            self._sel = self._base_sel | {idx}
        else:
            # nouvelle selection simple
            self._base_sel = set()
            self._anchor = idx
            self._sel = {idx}
        self.update()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        if self._mode == "new" and self._press is not None:
            self._rect = QRectF(self._press, pos).normalized()
            self.update()
        elif self._mode == "resize":
            self._resize_to(pos)
            self.update()
        elif self._mode == "textsel" and self._anchor is not None:
            idx = self._caret_index(pos)
            if idx is not None:
                self._sel = self._base_sel | self._range(self._anchor, idx)
                self.update()
        elif self._state == "ready":
            h = self._handle_at(pos)
            if h >= 0:
                self.setCursor(_CURSORS[h])
            elif self._rect and self._rect.normalized().contains(pos):
                self.setCursor(Qt.IBeamCursor)
            else:
                self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        mode = self._mode
        self._mode = None
        if mode in ("new", "resize"):
            self._request_ocr()

    def _select_all(self) -> None:
        if self._state != "ready" or not self._words:
            return
        self._sel = set(range(len(self._words)))
        self._anchor = 0
        self.update()

    # --- copie ---

    def _selected_words(self) -> list[Word]:
        return [self._words[i][0] for i in sorted(self._sel)]

    def _copy(self, words: list[Word]) -> None:
        text = full_text(words)
        if not text:
            self._panel.show_hint("Rien a copier.")
            return
        QGuiApplication.clipboard().setText(text)
        self._cancel()

    def _copy_all(self) -> None:
        if self._state == "ready":
            self._copy([w for w, _ in self._words])

    def _copy_selection(self) -> None:
        if self._sel:
            self._copy(self._selected_words())
        else:
            self._panel.show_hint("Glissez sur le texte, puis copiez.")

    def _copy_smart(self) -> None:
        if self._sel:
            self._copy_selection()
        else:
            self._copy_all()

    def _new_selection(self) -> None:
        self._glow.stop()
        self._state = "select"
        self._rect = None
        self._words = []
        self._lines = []
        self._sel.clear()
        self._anchor = None
        self._panel.set_busy(False)
        self._panel.show_hint("Glissez pour selectionner une zone de texte")
        self.setCursor(Qt.CrossCursor)
        self.update()

    # --- rendu ---

    def _tick(self) -> None:
        self._angle = (self._angle + 6) % 360
        self.update()

    def paintEvent(self, _event) -> None:
        if self._pix is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        full = self.rect()
        # fond : capture assombrie
        p.drawPixmap(full, self._pix)
        p.fillRect(full, QColor(0, 0, 0, 140))

        r = self._rect.normalized() if self._rect else None
        if r and r.width() >= 1 and r.height() >= 1:
            # zone nette (vrai contenu)
            p.drawPixmap(r, self._pix, QRectF(self._physical_rect(r)))
            # selection continue facon texte de page
            if self._state == "ready" and self._sel:
                self._paint_selection(p)
            # bordure / glow
            if self._state == "busy":
                self._paint_glow(p, r)
            else:
                p.setPen(QPen(_SEL_LINE, 1.5))
                p.setBrush(Qt.NoBrush)
                p.drawRect(r)
            if self._state == "ready":
                self._paint_handles(p, r)
        p.end()

    def _paint_selection(self, p: QPainter) -> None:
        """Surlignage bleu continu, une bande par ligne (comme sur une page web).

        La selection est decoupee en plages contigues (Ctrl peut en cumuler
        plusieurs) ; chaque plage est peinte ligne par ligne, du premier au
        dernier mot, sans coupure entre les mots d'une meme ligne.
        """
        sel = sorted(self._sel)
        runs: list[list[int]] = []
        run = [sel[0]]
        for i in sel[1:]:
            if i == run[-1] + 1:
                run.append(i)
            else:
                runs.append(run)
                run = [i]
        runs.append(run)

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 120, 255, 90))
        for run in runs:
            by_line: dict[tuple, list[int]] = {}
            for i in run:
                by_line.setdefault(self._words[i][0].line_key, []).append(i)
            for idxs in by_line.values():
                rects = [self._words[i][1] for i in idxs]
                left = min(x.left() for x in rects)
                right = max(x.right() for x in rects)
                top = min(x.top() for x in rects)
                bottom = max(x.bottom() for x in rects)
                band = QRectF(left - 2, top - 1, (right - left) + 4, (bottom - top) + 2)
                p.drawRoundedRect(band, 3, 3)

    def _paint_glow(self, p: QPainter, r: QRectF) -> None:
        grad = QConicalGradient(r.center(), self._angle)
        for pos, col in _GLOW_STOPS:
            grad.setColorAt(pos, col)
        for width, alpha in ((12, 60), (7, 130), (3, 235)):
            pen = QPen(QBrush(grad), width)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setOpacity(alpha / 255)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, 8, 8)
        p.setOpacity(1.0)

    def _paint_handles(self, p: QPainter, r: QRectF) -> None:
        p.setPen(QPen(QColor(255, 255, 255), 1))
        p.setBrush(QBrush(_SEL_LINE))
        s = 4.0
        for h in self._handles(r):
            p.drawRect(QRectF(h.x() - s, h.y() - s, 2 * s, 2 * s))

    # --- panel ---

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_panel()

    def _place_panel(self) -> None:
        self._panel.adjustSize()
        x = (self.width() - self._panel.width()) // 2
        self._panel.move(max(0, x), 24)
        self._panel.raise_()


class _TopPanel(QWidget):
    copy_all = Signal()
    copy_sel = Signal()
    select_all = Signal()
    retry = Signal()
    close_req = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        from PySide6.QtWidgets import QHBoxLayout, QLabel

        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            "_TopPanel { background: rgba(20,24,34,230); border-radius: 10px; }"
            "QLabel { color: #dfe6f2; font-size: 13px; }"
            "QPushButton { color: #eef2f8; background: rgba(255,255,255,18);"
            " border: 1px solid rgba(255,255,255,40); border-radius: 6px;"
            " padding: 5px 12px; }"
            "QPushButton:hover { background: rgba(0,170,255,120); }"
            "QPushButton:disabled { color: #7a8494; }"
        )
        self._hint = QLabel("")
        self._b_selall = QPushButton("Tout selectionner")
        self._b_sel = QPushButton("Copier selection")
        self._b_all = QPushButton("Copier tout")
        self._b_new = QPushButton("Nouvelle")
        self._b_close = QPushButton("Fermer")
        self._b_selall.clicked.connect(self.select_all)
        self._b_sel.clicked.connect(self.copy_sel)
        self._b_all.clicked.connect(self.copy_all)
        self._b_new.clicked.connect(self.retry)
        self._b_close.clicked.connect(self.close_req)
        for b in (self._b_selall, self._b_sel, self._b_all):
            b.setEnabled(False)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)
        lay.addWidget(self._hint)
        lay.addSpacing(6)
        lay.addWidget(self._b_selall)
        lay.addWidget(self._b_sel)
        lay.addWidget(self._b_all)
        lay.addWidget(self._b_new)
        lay.addWidget(self._b_close)

    def show_hint(self, text: str) -> None:
        self._hint.setText(text)
        self.adjustSize()

    def set_busy(self, busy: bool) -> None:
        if busy:
            self._hint.setText("Reconnaissance en cours...")
            for b in (self._b_selall, self._b_sel, self._b_all):
                b.setEnabled(False)
        self.adjustSize()

    def set_ready(self, count: int) -> None:
        self._hint.setText(
            f"{count} mots. Glissez sur le texte (Shift etend, Ctrl ajoute)."
            if count else "Aucun texte detecte. Ajustez la zone."
        )
        for b in (self._b_selall, self._b_sel, self._b_all):
            b.setEnabled(count > 0)
        self.adjustSize()
