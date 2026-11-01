"""
IGI (𒅆) — Context Preview Card & Quick Action Pills
Displays selected crop thumbnail, detected app context, WinRT OCR preview,
interactive full-resolution lightbox viewer, and 1-click action pills in solid grey.
"""

from __future__ import annotations

import io
from typing import Optional
from PIL import Image

try:
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QPixmap, QImage, QGuiApplication, QMouseEvent
    from PySide6.QtWidgets import (
        QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QFrame,
        QSizePolicy, QDialog, QScrollArea
    )
except ImportError:
    pass


class ImageLightboxDialog(QDialog):
    """Full-resolution modal lightbox view for captured visual screen crop."""

    def __init__(
        self,
        pil_image: Image.Image,
        app_title: str = "",
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self.setWindowTitle("IGI (𒅆) • Captured Selection Preview")
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1b22;
                border: 1px solid #3b3e4d;
                border-radius: 10px;
            }
        """)

        w, h = pil_image.size
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        # Header Bar
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        title_lbl = QLabel(f"IGI  𒅆  •  Captured Crop ({w} × {h} px)")
        title_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #f3f4f6;")
        header.addWidget(title_lbl)

        if app_title:
            app_chip = QLabel(app_title[:32])
            app_chip.setStyleSheet(
                "background-color: #262832; color: #a1a1aa; border-radius: 4px; padding: 2px 6px; font-size: 11px;"
            )
            header.addWidget(app_chip)

        header.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #a1a1aa; border: none; font-size: 14px; font-weight: bold; padding: 2px 8px; border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #2e303b; color: #ffffff;
            }
        """)
        close_btn.clicked.connect(self.accept)
        header.addWidget(close_btn)
        layout.addLayout(header)

        # Scrollable image display
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background-color: #121318; border: 1px solid #282a35; border-radius: 6px; }")

        img_container = QWidget()
        img_container.setStyleSheet("background: transparent;")
        c_layout = QVBoxLayout(img_container)
        c_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        buf = io.BytesIO()
        pil_image.save(buf, format="PNG")
        buf.seek(0)
        qimg = QImage.fromData(buf.getvalue())
        pix = QPixmap.fromImage(qimg)

        img_lbl = QLabel()
        img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_lbl.setPixmap(pix)
        c_layout.addWidget(img_lbl)

        scroll.setWidget(img_container)
        layout.addWidget(scroll, 1)

        # Calculate appropriate dialog size (up to 80% of screen)
        screen = QGuiApplication.primaryScreen()
        screen_geo = screen.availableGeometry() if screen else None
        max_w = int(screen_geo.width() * 0.80) if screen_geo else 960
        max_h = int(screen_geo.height() * 0.80) if screen_geo else 720

        target_w = min(max_w, max(460, w + 40))
        target_h = min(max_h, max(360, h + 80))
        self.resize(target_w, target_h)

        if parent:
            p_geo = parent.geometry()
            x = max(20, p_geo.center().x() - target_w // 2)
            y = max(20, p_geo.center().y() - target_h // 2)
            self.move(x, y)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.accept()
        else:
            super().keyPressEvent(event)


class ContextPreviewCard(QFrame):
    """Integrated solid card displaying thumbnail of segmented crop, active app name, and OCR preview."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("IgiContextCard")
        self.current_pil_image: Optional[Image.Image] = None
        self.current_app_title: str = ""
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # Thumbnail Image Label (Clickable to open full-resolution lightbox)
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(54, 54)
        self.thumb_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.thumb_label.setToolTip("Click to view full enlarged screenshot (Full Resolution)")
        self.thumb_label.setStyleSheet(
            "QLabel {"
            "  background-color: #18191d; border: 1px solid #30323c; border-radius: 6px;"
            "}"
            "QLabel:hover {"
            "  border: 1px solid #f59e0b;"
            "}"
        )
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.mousePressEvent = self._on_thumb_clicked
        layout.addWidget(self.thumb_label)

        # Details Column (App chip + OCR preview)
        details_layout = QVBoxLayout()
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(4)

        # Header row: App chip + Magnifier Pill
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(6)

        self.app_badge = QLabel("Desktop Workspace")
        self.app_badge.setObjectName("IgiAppBadge")
        self.app_badge.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        header_row.addWidget(self.app_badge)

        self.zoom_hint = QLabel("🔍 Click crop to enlarge")
        self.zoom_hint.setCursor(Qt.CursorShape.PointingHandCursor)
        self.zoom_hint.setStyleSheet("font-size: 10px; color: #71717a;")
        self.zoom_hint.mousePressEvent = self._on_thumb_clicked
        header_row.addWidget(self.zoom_hint)
        header_row.addStretch()

        details_layout.addLayout(header_row)

        # OCR snippet preview
        self.ocr_label = QLabel("No text detected")
        self.ocr_label.setObjectName("IgiOcrSnippet")
        self.ocr_label.setWordWrap(True)
        self.ocr_label.setMaximumHeight(36)
        details_layout.addWidget(self.ocr_label)

        layout.addLayout(details_layout)

    def _on_thumb_clicked(self, event: Optional[QMouseEvent] = None):
        """Open lightbox dialog when user clicks the crop thumbnail."""
        if self.current_pil_image:
            dlg = ImageLightboxDialog(
                self.current_pil_image,
                self.current_app_title,
                parent=self.window()
            )
            dlg.exec()

    def set_content(
        self,
        pil_image: Optional[Image.Image],
        app_title: str,
        ocr_text: str,
        window_context: Optional[Any] = None
    ):
        """Update thumbnail, application title, detected path/url badge, and OCR text preview."""
        self.current_pil_image = pil_image
        self.current_app_title = app_title or "Active Window"

        if pil_image:
            buf = io.BytesIO()
            pil_image.save(buf, format="PNG")
            buf.seek(0)
            qimg = QImage.fromData(buf.getvalue())
            pix = QPixmap.fromImage(qimg).scaled(
                54, 54,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            self.thumb_label.setPixmap(pix)
            self.thumb_label.setToolTip(f"Click to enlarge screenshot ({pil_image.width} × {pil_image.height} px)")
            self.zoom_hint.setText(f"🔍 Click to enlarge ({pil_image.width}×{pil_image.height})")
            self.zoom_hint.show()
        else:
            self.thumb_label.setText("📷")
            self.zoom_hint.hide()

        # Render rich context badge: detected folder path or URL if present
        if window_context and getattr(window_context, "detected_path", ""):
            p = window_context.detected_path
            p_short = p if len(p) <= 38 else "..." + p[-35:]
            self.app_badge.setText(f"📁 {p_short}")
            self.app_badge.setToolTip(f"Active Folder: {p}")
        elif window_context and getattr(window_context, "detected_url", ""):
            u = window_context.detected_url
            u_short = u if len(u) <= 40 else u[:37] + "..."
            self.app_badge.setText(f"🌐 {u_short}")
            self.app_badge.setToolTip(f"Active URL: {u}")
        elif window_context and getattr(window_context, "display_chip", ""):
            self.app_badge.setText(window_context.display_chip)
            self.app_badge.setToolTip(window_context.display_chip)
        else:
            short_title = self.current_app_title if len(self.current_app_title) <= 45 else self.current_app_title[:42] + "..."
            self.app_badge.setText(short_title)
            self.app_badge.setToolTip(self.current_app_title)

        clean_ocr = (ocr_text or "").strip().replace("\n", " ")
        if clean_ocr:
            preview = clean_ocr if len(clean_ocr) <= 75 else clean_ocr[:72] + "..."
            self.ocr_label.setText(preview)
            self.ocr_label.show()
        else:
            self.ocr_label.setText("Selected visual region")


class QuickActionsBar(QWidget):
    """Bar with 1-click action pills: Explain, Debug, Refactor, Copy in solid dark grey."""

    action_triggered = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 6)
        layout.setSpacing(6)

        actions = [
            ("⚡ Walkthrough", "walk through and explain the key elements on this screen"),
            ("Explain", "Explain what this is and how it works."),
            ("Fix / Debug", "Identify any bugs, errors, or issues and provide the exact fix."),
            ("Refactor", "Refactor this to be cleaner, faster, and more robust."),
            ("Summarize", "Summarize the key information and actionable points."),
            ("✕ Clear", "__CLEAR_OVERLAY__"),
        ]

        for i, (label, prompt) in enumerate(actions):
            btn = QPushButton(label)
            btn.setProperty("class", "IgiPill")
            if i == 0:
                btn.setStyleSheet(
                    "QPushButton {"
                    "  background-color: rgba(6, 182, 212, 0.15);"
                    "  border: 1px solid #06b6d4;"
                    "  color: #22d3ee;"
                    "  font-weight: bold;"
                    "  border-radius: 4px;"
                    "  padding: 4px 10px;"
                    "}"
                    "QPushButton:hover {"
                    "  background-color: rgba(6, 182, 212, 0.30);"
                    "  border: 1px solid #38bdf8;"
                    "}"
                )
            elif label == "✕ Clear":
                btn.setStyleSheet(
                    "QPushButton {"
                    "  background-color: rgba(239, 68, 68, 0.12);"
                    "  border: 1px solid rgba(239, 68, 68, 0.4);"
                    "  color: #f87171;"
                    "  border-radius: 4px;"
                    "  padding: 4px 8px;"
                    "}"
                    "QPushButton:hover {"
                    "  background-color: rgba(239, 68, 68, 0.25);"
                    "  border: 1px solid #ef4444;"
                    "}"
                )
            btn.clicked.connect(lambda checked=False, p=prompt: self.action_triggered.emit(p))
            layout.addWidget(btn)

        layout.addStretch()
