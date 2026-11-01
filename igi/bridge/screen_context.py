"""
IGI (𒅆) — OS Context & WinRT OCR Bridge
Extracts active foreground window information, detects active File Explorer directories and Browser URLs,
and runs native OCR on visual crops and full window captures.
"""

from __future__ import annotations

import io
import sys
import ctypes
import os
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Tuple
from PIL import Image

# Import memvision OCR if available
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "memvison" / "src"))

try:
    from memvision.ocr import LocalOCREngine
    _ocr_engine: Optional[LocalOCREngine] = LocalOCREngine(primary_engine="winrt", enabled=True)
except Exception:
    _ocr_engine = None


@dataclass
class WindowContext:
    title: str = ""
    process_name: str = ""
    pid: int = 0
    hwnd: int = 0
    rect: Tuple[int, int, int, int] = (0, 0, 0, 0)  # left, top, right, bottom
    detected_path: str = ""
    detected_url: str = ""
    full_window_ocr: str = ""

    @property
    def display_chip(self) -> str:
        proc = self.process_name or "Desktop"
        sub = self.detected_path or self.detected_url or self.title
        if sub:
            short = sub if len(sub) <= 45 else sub[:42] + "..."
            return f"{proc} — {short}"
        return proc


def detect_explorer_folder_path(hwnd: int = 0, title: str = "", ocr_text: str = "") -> Optional[str]:
    """Detect the active directory folder path of a File Explorer window."""
    clean_title = (title or "").replace(" - File Explorer", "").replace("File Explorer", "").strip()

    # 1. Match well-known Windows shell directories from title or full path in title
    if clean_title:
        # Check if title itself is a valid path
        if os.path.exists(clean_title):
            return os.path.abspath(clean_title)

        user_home = Path.home()
        known = {
            "Downloads": user_home / "Downloads",
            "Documents": user_home / "Documents",
            "Desktop": user_home / "Desktop",
            "Pictures": user_home / "Pictures",
            "Music": user_home / "Music",
            "Videos": user_home / "Videos",
            "Local Disk (C:)": Path("C:\\"),
            "C:": Path("C:\\"),
            "meta hackathon": Path(r"C:\meta hackathon"),
            "enheduanna": Path(r"C:\meta hackathon\enheduanna"),
            "enheduanna-submission": Path(r"C:\meta hackathon\enheduanna-submission"),
            "memvison": Path(r"C:\meta hackathon\memvison"),
            "cli-bridge": Path(r"C:\meta hackathon\cli-bridge"),
        }
        for name, p in known.items():
            if name.lower() in clean_title.lower() and p.exists():
                return str(p)

    # 2. Check OCR text for explicit Windows path (e.g. C:\... or D:\...)
    if ocr_text:
        match = re.search(r'([A-Za-z]:\\[A-Za-z0-9_\-\.\\]+)', ocr_text)
        if match:
            candidate = match.group(1).strip()
            if os.path.exists(candidate):
                return candidate

    # 3. Try Windows Shell.Application COM Dispatch if hwnd is valid
    if hwnd:
        try:
            import pythoncom
            pythoncom.CoInitialize()
            try:
                import win32com.client
                shell = win32com.client.Dispatch("Shell.Application")
                for window in shell.Windows():
                    try:
                        if int(window.HWND) == int(hwnd):
                            p = str(window.Document.Folder.Self.Path)
                            if p and os.path.exists(p):
                                return p
                    except Exception:
                        continue
            finally:
                pythoncom.CoUninitialize()
        except Exception:
            pass

    return None


def query_memvision_for_active_window(process_name: str, window_title: str) -> Tuple[Optional[str], Optional[str]]:
    """Query memvision.db for the latest capture matching the active window to retrieve url and file_path."""
    try:
        db_path = Path(r"C:\meta hackathon\memvison\data\memvision.db")
        if not db_path.exists():
            return None, None
        import sqlite3
        conn = sqlite3.connect(str(db_path), timeout=0.5)
        cur = conn.cursor()
        cur.execute(
            "SELECT url, file_path FROM captures WHERE app_name LIKE ? OR window_title LIKE ? ORDER BY id DESC LIMIT 1",
            (f"%{process_name}%", f"%{window_title[:24]}%")
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return row[0], row[1]
    except Exception:
        pass
    return None, None


def detect_browser_url(process_name: str, window_title: str, ocr_text: str = "") -> Optional[str]:
    """Detect active URL for web browsers via memvision capture or OCR address bar."""
    # 1. Query memvision DB for active browser capture
    url, _ = query_memvision_for_active_window(process_name, window_title)
    if url:
        return url

    # 2. Check full-window OCR for address bar pattern
    if ocr_text:
        match = re.search(r'(https?://[a-zA-Z0-9_\-\.\/\?\=\&\%\+\#\:\@]+)', ocr_text)
        if match:
            url_str = match.group(1).rstrip(".,;:)")
            return url_str

    return None


def get_active_window_context() -> WindowContext:
    """Retrieve details for the current foreground window on Windows."""
    context = WindowContext()

    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return context

        context.hwnd = hwnd

        # Window Title
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            context.title = buff.value

        # Window Rect
        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        rect = RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            context.rect = (rect.left, rect.top, rect.right, rect.bottom)

        # Process ID
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        context.pid = pid.value

        # Executable name via psutil / Win32
        try:
            import psutil
            proc = psutil.Process(context.pid)
            context.process_name = proc.name()
        except Exception:
            context.process_name = "Application"

        # If the active foreground window is IGI itself (e.g. user had HUD in focus),
        # walk down the desktop Z-order to find the true underlying application window!
        t_low = (context.title or "").lower()
        p_low = (context.process_name or "").lower()
        is_igi = (
            context.pid == os.getpid()
            or "python" in p_low
            or "igi" in t_low
            or "enheduanna" in t_low
            or not context.title
            or t_low in ("python", "pythonw", "application")
        )

        if is_igi:
            next_hwnd = user32.GetWindow(hwnd, 2)  # GW_HWNDNEXT
            attempts = 0
            found_app = False
            while next_hwnd and attempts < 35:
                attempts += 1
                if user32.IsWindowVisible(next_hwnd) and not user32.IsIconic(next_hwnd):
                    next_pid = ctypes.c_ulong()
                    user32.GetWindowThreadProcessId(next_hwnd, ctypes.byref(next_pid))
                    if next_pid.value == os.getpid():
                        next_hwnd = user32.GetWindow(next_hwnd, 2)
                        continue

                    nproc_name = ""
                    try:
                        import psutil
                        nproc_name = psutil.Process(next_pid.value).name().lower()
                    except Exception:
                        pass

                    if "python" in nproc_name:
                        next_hwnd = user32.GetWindow(next_hwnd, 2)
                        continue

                    next_len = user32.GetWindowTextLengthW(next_hwnd)
                    if next_len > 0:
                        nbuff = ctypes.create_unicode_buffer(next_len + 1)
                        user32.GetWindowTextW(next_hwnd, nbuff, next_len + 1)
                        ntitle = nbuff.value
                        nt_low = ntitle.lower()
                        ignore_titles = (
                            "program manager", "windows input experience", "task switching",
                            "settings", "gdi+", "nvidia geforce overlay"
                        )
                        if (
                            ntitle
                            and not any(ig in nt_low for ig in ignore_titles)
                            and "igi" not in nt_low
                            and "enheduanna" not in nt_low
                        ):
                            context.hwnd = next_hwnd
                            context.title = ntitle
                            if user32.GetWindowRect(next_hwnd, ctypes.byref(rect)):
                                context.rect = (rect.left, rect.top, rect.right, rect.bottom)
                            context.pid = next_pid.value
                            context.process_name = nproc_name or "Application"
                            found_app = True
                            break
                next_hwnd = user32.GetWindow(next_hwnd, 2)

            if not found_app:
                context.title = "Desktop Workspace"
                context.process_name = "Desktop"
                context.rect = (0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))

    except Exception:
        context.title = "Desktop Workspace"
        context.process_name = "Explorer"

    return context


def get_window_context_at_point(x: int, y: int) -> Optional[WindowContext]:
    """Retrieve top-level window context at desktop screen coordinates (x, y)."""
    try:
        user32 = ctypes.windll.user32
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        pt = POINT(int(x), int(y))
        hwnd = user32.WindowFromPoint(pt)
        if not hwnd:
            return None
        root_hwnd = user32.GetAncestor(hwnd, 2)  # GA_ROOT = 2
        if not root_hwnd:
            root_hwnd = hwnd

        ctx = WindowContext()
        ctx.hwnd = root_hwnd

        length = user32.GetWindowTextLengthW(root_hwnd)
        if length > 0:
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(root_hwnd, buff, length + 1)
            ctx.title = buff.value

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]
        rect = RECT()
        if user32.GetWindowRect(root_hwnd, ctypes.byref(rect)):
            ctx.rect = (rect.left, rect.top, rect.right, rect.bottom)

        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(root_hwnd, ctypes.byref(pid))
        ctx.pid = pid.value

        try:
            import psutil
            ctx.process_name = psutil.Process(ctx.pid).name()
        except Exception:
            ctx.process_name = "Application"

        return ctx
    except Exception:
        return None


def enrich_window_context(context: WindowContext, full_window_crop: Optional[Image.Image] = None):
    """Enrich window context with full OCR, detected folder path, and browser URL."""
    if full_window_crop:
        context.full_window_ocr = extract_text_from_crop(full_window_crop)

    p_lower = (context.process_name or "").lower()

    # 1. File Explorer
    if "explorer" in p_lower:
        folder = detect_explorer_folder_path(context.hwnd, context.title, context.full_window_ocr)
        if folder:
            context.detected_path = folder

    # 2. Web Browsers
    elif any(b in p_lower for b in ("brave", "chrome", "msedge", "firefox", "opera", "vivaldi")):
        url = detect_browser_url(context.process_name, context.title, context.full_window_ocr)
        if url:
            context.detected_url = url

    # 3. Editors & IDEs (Antigravity, VS Code, Cursor)
    elif any(e in p_lower for e in ("antigravity", "code", "cursor", "pycharm", "sublime")):
        _, f_path = query_memvision_for_active_window(context.process_name, context.title)
        if f_path:
            context.detected_path = f_path


def extract_text_from_crop(image: Optional[Image.Image]) -> str:
    """Run native Windows WinRT OCR on a cropped PIL Image synchronously in milliseconds."""
    if not image or image.width < 10 or image.height < 10:
        return ""

    try:
        import winrt._winrt
        winrt._winrt.init_apartment(winrt._winrt.MTA)
        import winrt.windows.graphics.imaging as imaging
        import winrt.windows.storage.streams as streams
        import winrt.windows.media.ocr as winrt_ocr

        eng = winrt_ocr.OcrEngine.try_create_from_user_profile_languages()
        if not eng:
            return ""

        rgba = image.convert("RGBA")
        writer = streams.DataWriter()
        writer.write_bytes(rgba.tobytes())
        buf = writer.detach_buffer()

        sb = imaging.SoftwareBitmap(
            imaging.BitmapPixelFormat.RGBA8,
            rgba.width,
            rgba.height,
            imaging.BitmapAlphaMode.PREMULTIPLIED
        )
        sb.copy_from_buffer(buf)

        op = eng.recognize_async(sb)
        res = op.get()
        return res.text.strip() if res and res.text else ""
    except Exception:
        return ""
