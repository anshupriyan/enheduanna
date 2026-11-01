"""
IGI (𒅆) — Fullscreen Interactive Drawing Canvas
Captures desktop snapshot, renders smooth glowing stylus strokes, and extracts SAM crops.
"""

from __future__ import annotations

import io
from typing import List, Tuple, Optional, Callable
from PIL import Image

try:
    from PySide6.QtCore import Qt, QPoint, QRect, Signal
    from PySide6.QtGui import (
        QPainter, QPen, QColor, QBrush, QPixmap, QImage, QCursor, QPaintEvent, QMouseEvent, QKeyEvent
    )
    from PySide6.QtWidgets import QWidget, QApplication
except ImportError:
    pass

import mss

try:
    from ..sam.router import DualMoESAMRouter
    from ..bridge.screen_context import (
        get_active_window_context, get_window_context_at_point, extract_text_from_crop, enrich_window_context, WindowContext
    )
except (ImportError, ValueError):
    from sam.router import DualMoESAMRouter
    from bridge.screen_context import (
        get_active_window_context, get_window_context_at_point, extract_text_from_crop, enrich_window_context, WindowContext
    )


class IgiCanvasOverlay(QWidget):
    """Fullscreen translucent drawing overlay for circle-to-search gestures."""

    selection_completed = Signal(object, str, str, str, object)  # crop(PIL), ocr_text, win_title, proc_name, WindowContext

    def __init__(self, sam_router: Optional[DualMoESAMRouter] = None):
        super().__init__()
        self.sam_router = sam_router or DualMoESAMRouter()
        self.stroke_points: List[Tuple[int, int]] = []
        self.is_drawing = False
        self.desktop_screenshot: Optional[Image.Image] = None
        self.cached_pixmap: Optional[QPixmap] = None
        self.active_context: Optional[WindowContext] = None

        self._init_window()

    def _init_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def freeze_screen_and_show(self):
        """Take instant screen snapshot (<15ms via mss) and show overlay."""
        # 1. Capture active foreground window BEFORE overlay steals focus
        self.active_context = get_active_window_context()

        # 2. Fast desktop capture
        with mss.mss() as sct:
            monitor = sct.monitors[0]  # Full virtual screen
            sct_img = sct.grab(monitor)
            self.desktop_screenshot = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

        # Convert to QPixmap for high-performance blitting
        buf = io.BytesIO()
        self.desktop_screenshot.save(buf, format="JPEG", quality=85)
        buf.seek(0)
        qimg = QImage.fromData(buf.getvalue())
        self.cached_pixmap = QPixmap.fromImage(qimg)

        # 3. Geometry & Show
        screen = QApplication.primaryScreen()
        geo = screen.geometry()
        self.setGeometry(geo)
        self.stroke_points = []
        self.is_drawing = False
        self.showFullScreen()
        self.raise_()
        self.activateWindow()

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Draw frozen desktop snapshot with slight focus dim
        if self.cached_pixmap:
            painter.drawPixmap(0, 0, self.cached_pixmap)
            # Subtle dark vignette / focus scrim
            painter.fillRect(self.rect(), QColor(13, 15, 18, 55))

        # Draw user's drawn stylus circle / lasso
        if len(self.stroke_points) >= 2:
            # Outer amber glow
            glow_pen = QPen(QColor(245, 158, 11, 80), 8)
            glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            glow_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(glow_pen)

            for i in range(len(self.stroke_points) - 1):
                p1 = QPoint(*self.stroke_points[i])
                p2 = QPoint(*self.stroke_points[i + 1])
                painter.drawLine(p1, p2)

            # Core sharp neon amber line
            core_pen = QPen(QColor(251, 191, 36, 235), 3)
            core_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            core_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(core_pen)

            for i in range(len(self.stroke_points) - 1):
                p1 = QPoint(*self.stroke_points[i])
                p2 = QPoint(*self.stroke_points[i + 1])
                painter.drawLine(p1, p2)

            # Connect loop if releasing
            if not self.is_drawing and len(self.stroke_points) > 4:
                p_first = QPoint(*self.stroke_points[0])
                p_last = QPoint(*self.stroke_points[-1])
                painter.drawLine(p_last, p_first)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_drawing = True
            self.stroke_points = [(event.pos().x(), event.pos().y())]
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.is_drawing:
            self.stroke_points.append((event.pos().x(), event.pos().y()))
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self.is_drawing:
            self.is_drawing = False
            self.update()
            self._process_selection()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()

    def _process_selection(self):
        """Invoke SAM 2 geometric snapping, run OCR, and emit result to HUD."""
        if not self.desktop_screenshot or len(self.stroke_points) < 3:
            self.hide()
            return

        # 1. Route to SAM 2 geometric snapping engine
        result = self.sam_router.route_gesture(self.desktop_screenshot, self.stroke_points)
        crop_img: Image.Image = result["crop"]

        # 2. Native WinRT OCR on the cropped element
        ocr_text = extract_text_from_crop(crop_img)

        # 3. Context metadata & full-window enrichment
        # If user circled an application window, resolve the window at the stroke centroid
        if len(self.stroke_points) > 0:
            cx = sum(p[0] for p in self.stroke_points) // len(self.stroke_points)
            cy = sum(p[1] for p in self.stroke_points) // len(self.stroke_points)
            pt_ctx = get_window_context_at_point(cx, cy)
            if pt_ctx:
                t_low = (self.active_context.title if self.active_context else "").lower()
                p_low = (self.active_context.process_name if self.active_context else "").lower()
                pt_t_low = (pt_ctx.title or "").lower()
                if "igi" in t_low or "enheduanna" in t_low or "python" in p_low or (pt_ctx.title and "igi" not in pt_t_low):
                    if "igi" not in pt_t_low and "enheduanna" not in pt_t_low:
                        self.active_context = pt_ctx

        win_title = self.active_context.title if self.active_context else ""
        proc_name = self.active_context.process_name if self.active_context else ""

        full_win_crop = None
        if self.active_context and self.active_context.rect and self.desktop_screenshot:
            l, t, r, b = self.active_context.rect
            w, h = self.desktop_screenshot.size
            l = max(0, min(l, w - 1))
            t = max(0, min(t, h - 1))
            r = max(l + 1, min(r, w))
            b = max(t + 1, min(b, h))
            if r > l and b > t:
                try:
                    full_win_crop = self.desktop_screenshot.crop((l, t, r, b))
                except Exception:
                    pass

        if self.active_context:
            try:
                enrich_window_context(self.active_context, full_win_crop)
            except Exception:
                pass

        self.hide()
        # Emit signal to show in HUD with complete window context
        self.selection_completed.emit(crop_img, ocr_text, win_title, proc_name, self.active_context)
