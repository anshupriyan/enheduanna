"""
IGI (𒅆) — The Eye of Enheduanna
Main Entry Point: Launches the visual companion, global hotkey daemon, and system tray.
"""

from __future__ import annotations

import sys
import os
from pathlib import Path

# Add package directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from PySide6.QtCore import Qt, QTimer, Signal, QObject
    from PySide6.QtGui import QIcon, QAction
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
except ImportError:
    print("[IGI Error] PySide6 is required. Please install via: pip install PySide6")
    sys.exit(1)

from config import load_config
from overlay.canvas import IgiCanvasOverlay
from overlay.hotkey import GlobalHotkeyManager
from hud.chat_window import IgiHudWindow
from sam.router import DualMoESAMRouter


class HotkeyBridge(QObject):
    triggered = Signal()


def main():
    config = load_config()

    # Enable High DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Enheduanna IGI (𒅆)")

    # 1. Initialize Dual MoE SAM Router
    sam_router = DualMoESAMRouter()

    # 2. Initialize Selection Canvas (Screen projections disabled to keep desktop clean)
    overlay = IgiCanvasOverlay(sam_router=sam_router)

    # 3. Initialize Floating HUD Window (Bottom-Right, no projector overlay)
    hud = IgiHudWindow(config=config, projector=None, sam_router=sam_router)

    # 4. Wire Selection: Canvas Release -> HUD Preview & Focus
    overlay.selection_completed.connect(hud.set_selection_context)

    # 5. Wire Hotkey: Ctrl+Shift+Q -> Freeze Screen & Show Drawing Canvas
    hotkey_bridge = HotkeyBridge()
    hotkey_bridge.triggered.connect(overlay.freeze_screen_and_show)

    hotkey_mgr = GlobalHotkeyManager(
        hotkey_str=config.hud.hotkey,
        on_trigger=lambda: hotkey_bridge.triggered.emit()
    )
    hotkey_mgr.start()

    # 6. System Tray Icon & Menu
    from PySide6.QtGui import QPixmap, QPainter, QColor
    tray_pixmap = QPixmap(32, 32)
    tray_pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(tray_pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#f59e0b"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, 28, 28)
    painter.setBrush(QColor("#0d0f12"))
    painter.drawEllipse(7, 7, 18, 18)
    painter.setBrush(QColor("#f59e0b"))
    painter.drawEllipse(12, 12, 8, 8)
    painter.end()
    tray_icon = QIcon(tray_pixmap)
    app.setWindowIcon(tray_icon)

    tray = QSystemTrayIcon(tray_icon, app)
    tray.setToolTip("IGI (𒅆) — The Eye of Enheduanna\nPress Ctrl+Shift+Q to Circle-to-Search")

    tray_menu = QMenu()
    act_circle = QAction("𒅆 Circle to Search (Ctrl+Shift+Q)", tray_menu)
    act_circle.triggered.connect(overlay.freeze_screen_and_show)
    tray_menu.addAction(act_circle)

    act_hud = QAction("Open Companion HUD", tray_menu)
    act_hud.triggered.connect(lambda: (hud.show(), hud.raise_(), hud.activateWindow()))
    tray_menu.addAction(act_hud)

    tray_menu.addSeparator()

    act_quit = QAction("Exit IGI", tray_menu)
    act_quit.triggered.connect(lambda: (hotkey_mgr.stop(), app.quit()))
    tray_menu.addAction(act_quit)

    tray.setContextMenu(tray_menu)
    tray.show()

    print("=" * 65)
    print("   ::: IGI (𒅆) — THE EYE OF ENHEDUANNA IS ACTIVE :::")
    print(f"   • Shortcut:        {config.hud.hotkey} (Circle anything on screen)")
    print(f"   • Core Server:     {config.server.base_url}")
    print(f"   • Tool Model:      {config.model.tool_model} (Spark 1.3)")
    print(f"   • Synthesis Model: {config.model.synthesis_model} (Wonder 1.0)")
    print(f"   • Grounder:        Local Geometric Snapping + Native Optical OCR Grounding")
    print("=" * 65)

    # Show HUD on initial launch
    hud.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

