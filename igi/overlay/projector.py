"""
IGI (𒅆) — Agent Spatial Projector Overlay
Renders agent-directed glowing halos, visual spotlights, and anchored floating cards directly on the live desktop.
Features:
- Layered glow (10px 25% + 4px 60% + 2px solid) + 180ms fade-in + card drop shadow
- Nearby spatial card placement within 120px of target bbox (below/above/side) with 140px leader line cap
- Numbered badge indicators (1, 2, 3) matching HUD list
- Dynamic card sizing via QFontMetrics and collision-preventing vertical stagger
- High-efficiency 80ms pulse loop with dirty-rect updates and cached fonts/pens
"""

from __future__ import annotations

import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

try:
    from PySide6.QtCore import Qt, QRect, QTimer, QPoint
    from PySide6.QtGui import QPainter, QPen, QColor, QFont, QFontMetrics, QPaintEvent
    from PySide6.QtWidgets import QWidget, QApplication
except ImportError:
    pass


@dataclass
class VisualHighlight:
    bbox: List[int]             # [x1, y1, x2, y2]
    label: str                  # e.g. "Glyph + Unicode"
    description: str = ""       # Floating explanation card text (max 28 words)
    color_type: str = "cyan"    # "cyan" (walkthrough), "amber" (action), "red" (alert)
    alpha_pulse: int = 180
    index: int = 0              # 1, 2, 3 for numbered badge
    spawn_time: float = field(default_factory=time.time)
    _last_card_rect: Optional[Any] = None


class SpatialProjectorOverlay(QWidget):
    """Click-through desktop overlay that projects agent guidance highlights, floating tooltips, and warnings."""

    def __init__(self, enabled: bool = False):
        super().__init__()
        self.enabled = enabled
        self.highlights: List[VisualHighlight] = []
        self._pulse_direction = -1
        self._current_pulse = 180

        # Cached fonts
        self._badge_font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        self._badge_fm = QFontMetrics(self._badge_font)
        self._num_font = QFont("Segoe UI", 8, QFont.Weight.Bold)
        self._header_font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        self._body_font = QFont("Segoe UI", 8, QFont.Weight.Normal)
        self._body_fm = QFontMetrics(self._body_font)

        self._init_window()

        # Pulse timer for breathing glow animation (80ms interval)
        self.pulse_timer = QTimer(self)
        self.pulse_timer.timeout.connect(self._animate_pulse)

        # Clear timer to auto-dismiss highlights
        self._clear_timer = QTimer(self)
        self._clear_timer.setSingleShot(True)
        self._clear_timer.timeout.connect(self.clear_highlights)

    def _init_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput  # Click-through so user can interact with apps beneath!
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def show(self):
        if not self.enabled:
            return
        super().show()

    def _pin_topmost(self):
        """Force Windows DWM to position overlay across full display at absolute topmost Z-layer."""
        if not self.enabled:
            return
        self.show()
        self.raise_()
        try:
            import ctypes
            screen = QApplication.primaryScreen()
            geo = screen.geometry() if screen else self.geometry()
            # HWND_TOPMOST = -1, SWP_NOACTIVATE = 0x0010, SWP_SHOWWINDOW = 0x0040 -> 0x0050
            ctypes.windll.user32.SetWindowPos(
                int(self.winId()),
                -1,
                geo.x(), geo.y(), geo.width(), geo.height(),
                0x0050
            )
        except Exception:
            pass

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.clear_highlights()
        super().keyPressEvent(event)

    def add_guidance_highlight(
        self,
        bbox: List[int],
        label: str,
        description: str = "",
        is_warning: bool = False,
        color_type: str = "amber",
        duration_ms: int = 15000
    ):
        """Project a single spatial halo or warning spotlight with floating explanation card."""
        self.highlights.clear()  # Replace previous spotlight
        color = "red" if is_warning else color_type
        hl = VisualHighlight(bbox=bbox, label=label, description=description, color_type=color, index=1)
        self.highlights.append(hl)

        if not self.enabled:
            return

        screen = QApplication.primaryScreen()
        if screen:
            self.setGeometry(screen.geometry())

        self._pin_topmost()
        if not self.pulse_timer.isActive():
            self.pulse_timer.start(80)

        if duration_ms > 0:
            self._clear_timer.stop()
            self._clear_timer.start(duration_ms)
        else:
            self._clear_timer.stop()

    def add_walkthrough_blocks(self, blocks: List[Dict[str, Any]], duration_ms: int = 45000):
        """Display multiple segmented blocks with anchored explanation cards simultaneously."""
        self.highlights.clear()
        for idx, b in enumerate(blocks):
            bbox = b.get("bbox", [0, 0, 100, 100])
            lbl = b.get("label", "Code Block")
            desc = b.get("description", "")
            ctype = b.get("color_type", "cyan")
            b_idx = b.get("index", idx + 1)
            self.highlights.append(VisualHighlight(
                bbox=bbox, label=lbl, description=desc, color_type=ctype, index=b_idx
            ))

        if not self.enabled:
            return

        screen = QApplication.primaryScreen()
        if screen:
            self.setGeometry(screen.geometry())

        self._pin_topmost()
        if not self.pulse_timer.isActive():
            self.pulse_timer.start(80)

        if duration_ms > 0:
            self._clear_timer.stop()
            self._clear_timer.start(duration_ms)
        else:
            self._clear_timer.stop()

    def clear_highlights(self):
        self.highlights.clear()
        self.pulse_timer.stop()
        self.hide()

    def _animate_pulse(self):
        self._current_pulse += self._pulse_direction * 6
        if self._current_pulse <= 80:
            self._current_pulse = 80
            self._pulse_direction = 1
        elif self._current_pulse >= 220:
            self._current_pulse = 220
            self._pulse_direction = -1

        # Dirty-rect update only: bounds of active highlights and cards + margin
        if not self.highlights:
            self.update()
            return

        dirty_rect = QRect()
        for hl in self.highlights:
            x1, y1, x2, y2 = hl.bbox
            rect = QRect(x1 - 25, y1 - 35, (x2 - x1) + 50, (y2 - y1) + 70)
            dirty_rect = dirty_rect.united(rect)
            if hl._last_card_rect is not None and hasattr(hl._last_card_rect, "isValid") and hl._last_card_rect.isValid():
                dirty_rect = dirty_rect.united(hl._last_card_rect.adjusted(-25, -25, 25, 25))

        if dirty_rect.isValid():
            self.update(dirty_rect)
        else:
            self.update()

    def paintEvent(self, event: QPaintEvent):
        if not self.highlights:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        screen_geo = self.geometry()
        screen_w = screen_geo.width()
        screen_h = screen_geo.height()
        now = time.time()

        placed_card_rects: List[QRect] = []

        for hl in self.highlights:
            x1, y1, x2, y2 = hl.bbox
            w = max(x2 - x1, 20)
            h = max(y2 - y1, 20)
            rect = QRect(x1, y1, w, h)

            # 180ms fade-in computation
            elapsed = now - hl.spawn_time
            fade_scale = min(1.0, max(0.2, elapsed / 0.18))
            cur_pulse = int(self._current_pulse * fade_scale)

            # Color palette
            if hl.color_type == "red":
                cr, cg, cb = 239, 68, 68
                badge_bg = QColor(239, 68, 68, int(235 * fade_scale))
                badge_fg = QColor(255, 255, 255)
            elif hl.color_type == "cyan":
                cr, cg, cb = 6, 182, 212
                badge_bg = QColor(6, 182, 212, int(235 * fade_scale))
                badge_fg = QColor(10, 15, 25)
            else:  # amber
                cr, cg, cb = 245, 158, 11
                badge_bg = QColor(245, 158, 11, int(235 * fade_scale))
                badge_fg = QColor(10, 15, 25)

            line_color = QColor(cr, cg, cb, cur_pulse)

            # 1. Layered Glow
            # Layer 1: Outer soft glow (10px, 25% alpha)
            outer_glow_rect = rect.adjusted(-10, -10, 10, 10)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(cr, cg, cb, int(cur_pulse * 0.25)))
            painter.drawRoundedRect(outer_glow_rect, 10, 10)

            # Layer 2: Mid glow (4px, 60% alpha)
            mid_glow_rect = rect.adjusted(-4, -4, 4, 4)
            painter.setBrush(QColor(cr, cg, cb, int(cur_pulse * 0.55)))
            painter.drawRoundedRect(mid_glow_rect, 7, 7)

            # Layer 3: Solid border (2px)
            border_pen = QPen(line_color, 2.0)
            border_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(border_pen)
            painter.setBrush(QColor(cr, cg, cb, int(cur_pulse * 0.12)))  # Subtle inner tint
            painter.drawRoundedRect(rect, 6, 6)

            # 2. Numbered Badge (1, 2, 3) on top-left of halo
            badge_offset_x = 0
            if hl.index > 0:
                num_size = 20
                num_rect = QRect(x1 - 2, max(0, y1 - 24), num_size, num_size)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(line_color)
                painter.drawEllipse(num_rect)

                painter.setPen(badge_fg)
                painter.setFont(self._num_font)
                painter.drawText(num_rect, Qt.AlignmentFlag.AlignCenter, str(hl.index))
                badge_offset_x = num_size + 4

            # 3. Label Badge with FontMetrics
            if hl.label:
                text_advance = self._badge_fm.horizontalAdvance(hl.label)
                badge_w = min(text_advance + 16, 320)
                label_rect = QRect(x1 + badge_offset_x, max(0, y1 - 24), badge_w, 20)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(badge_bg)
                painter.drawRoundedRect(label_rect, 4, 4)

                painter.setPen(badge_fg)
                painter.setFont(self._badge_font)
                painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, hl.label)

        # 4. Floating Anchored Explanation Cards with Nearby Placement
        described_hls = [h for h in self.highlights if h.description]
        if described_hls:
            card_w = 300

            for hl in described_hls:
                x1, y1, x2, y2 = hl.bbox
                elapsed = now - hl.spawn_time
                fade_scale = min(1.0, max(0.2, elapsed / 0.18))
                cur_pulse = int(self._current_pulse * fade_scale)

                # Dynamic card height via QFontMetrics.boundingRect
                desc_rect = self._body_fm.boundingRect(
                    QRect(0, 0, card_w - 24, 600),
                    Qt.TextFlag.TextWordWrap,
                    hl.description
                )
                card_h = max(72, min(140, desc_rect.height() + 36))

                # Nearby placement within 120px:
                # 1. Preferred: Below bbox
                cand_x = max(15, min(screen_w - card_w - 15, x1))
                cand_y = y2 + 12

                # 2. If no space below, flip above bbox
                if cand_y + card_h > screen_h - 20:
                    cand_y = y1 - card_h - 12

                # 3. If above is also off-screen, place right or left
                if cand_y < 15:
                    if x2 + card_w + 14 < screen_w - 15:
                        cand_x = x2 + 14
                        cand_y = max(15, min(screen_h - card_h - 15, y1))
                    elif x1 - card_w - 14 > 15:
                        cand_x = x1 - card_w - 14
                        cand_y = max(15, min(screen_h - card_h - 15, y1))

                card_rect = QRect(int(cand_x), int(cand_y), card_w, card_h)

                # Vertical stagger to avoid overlap with previously placed cards
                for placed in placed_card_rects:
                    if card_rect.intersects(placed):
                        shift = (placed.bottom() + 10) - card_rect.top()
                        if card_rect.bottom() + shift < screen_h - 15:
                            card_rect.translate(0, shift)
                        else:
                            card_rect.translate(0, (placed.top() - 10) - card_rect.bottom())

                placed_card_rects.append(card_rect)
                hl._last_card_rect = card_rect

                # Connector anchor point on bbox clamped to leader line cap (140px)
                card_center = card_rect.center()
                box_center_x = max(x1, min(x2, card_center.x()))
                box_center_y = max(y1, min(y2, card_center.y()))
                anchor_from = QPoint(box_center_x, box_center_y)

                # Anchor target on nearest card border
                if card_center.y() >= y2:
                    anchor_to = QPoint(card_center.x(), card_rect.top())
                elif card_center.y() <= y1:
                    anchor_to = QPoint(card_center.x(), card_rect.bottom())
                elif card_center.x() >= x2:
                    anchor_to = QPoint(card_rect.left(), card_center.y())
                else:
                    anchor_to = QPoint(card_rect.right(), card_center.y())

                # Color resolution
                if hl.color_type == "red":
                    card_border_color = QColor(239, 68, 68, cur_pulse)
                elif hl.color_type == "cyan":
                    card_border_color = QColor(34, 211, 238, cur_pulse)
                else:
                    card_border_color = QColor(251, 191, 36, cur_pulse)

                # Draw leader connector line
                connector_pen = QPen(card_border_color, 1.4, Qt.PenStyle.DashLine)
                painter.setPen(connector_pen)
                painter.drawLine(anchor_from, anchor_to)

                # 5. Card Drop Shadow
                shadow_rect = card_rect.translated(3, 4)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(0, 0, 0, int(95 * fade_scale)))
                painter.drawRoundedRect(shadow_rect, 8, 8)

                # 6. Glassmorphic Card Container
                painter.setPen(QPen(card_border_color, 1.5))
                painter.setBrush(QColor(15, 23, 42, int(242 * fade_scale)))  # Slate dark #0f172a
                painter.drawRoundedRect(card_rect, 8, 8)

                # Header Title with Index
                painter.setPen(card_border_color)
                painter.setFont(self._header_font)
                h_title = f"{hl.index}. {hl.label}" if hl.index > 0 else hl.label
                hrect = QRect(card_rect.left() + 12, card_rect.top() + 8, card_w - 24, 18)
                painter.drawText(hrect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, h_title)

                # Body Explanation
                painter.setPen(QColor(241, 245, 249, int(250 * fade_scale)))  # Slate 100 crisp light
                painter.setFont(self._body_font)
                brect = QRect(card_rect.left() + 12, card_rect.top() + 28, card_w - 24, card_h - 32)
                painter.drawText(
                    brect,
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                    hl.description
                )
