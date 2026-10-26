"""
Windows Window Context and Browser URL Extractor for mem-vision-mcp.
Extracts active foreground window, process name, window title, and active browser tab URLs via UI Automation.
"""

from __future__ import annotations

import concurrent.futures
import ctypes
from ctypes import wintypes
import logging
import time
from dataclasses import dataclass
from typing import Optional, Tuple
import psutil

logger = logging.getLogger(__name__)

# Known browser process names
BROWSER_PROCESSES = {
    "chrome.exe",
    "msedge.exe",
    "brave.exe",
    "firefox.exe",
    "opera.exe",
    "vivaldi.exe",
    "arc.exe",
    "waterfox.exe",
}


def _init_context_thread() -> bool:
    """Attaches worker thread to interactive desktop WinSta0\\default."""
    try:
        u32 = ctypes.windll.user32
        u32.OpenWindowStationW.restype = wintypes.HANDLE
        u32.OpenWindowStationW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL, wintypes.DWORD]
        u32.SetProcessWindowStation.restype = wintypes.BOOL
        u32.SetProcessWindowStation.argtypes = [wintypes.HANDLE]
        u32.OpenDesktopW.restype = wintypes.HANDLE
        u32.OpenDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        u32.SetThreadDesktop.restype = wintypes.BOOL
        u32.SetThreadDesktop.argtypes = [wintypes.HANDLE]

        hwinsta = u32.OpenWindowStationW("winsta0", False, 0x10000000)
        if hwinsta:
            u32.SetProcessWindowStation(hwinsta)
            hdesk = u32.OpenDesktopW("default", 0, False, 0x10000000)
            if hdesk:
                u32.SetThreadDesktop(hdesk)
                return True
    except Exception as e:
        logger.debug("Desktop attachment failed in context thread: %s", e)
    return False


@dataclass
class WindowContext:
    hwnd: int
    process_id: int
    app_name: str
    window_title: str
    url: Optional[str] = None
    bounding_box: Optional[Tuple[int, int, int, int]] = None
    is_browser: bool = False


class ContextExtractor:
    """
    Extracts rich desktop context from the active foreground window.
    Uses Win32 APIs and UI Automation for browser URL extraction.
    """

    def __init__(self, uia_timeout_seconds: float = 0.5):
        self.uia_timeout = uia_timeout_seconds
        self._last_hwnd: Optional[int] = None
        self._last_title: Optional[str] = None
        self._last_url: Optional[str] = None
        self._last_url_time: float = 0.0
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="memvision_context",
            initializer=_init_context_thread,
        )

    def _get_active_context_worker(self) -> WindowContext:
        """Worker executing on interactive desktop thread."""
        u32 = ctypes.windll.user32
        hwnd = u32.GetForegroundWindow()

        # Fallback to topmost visible window in desktop z-order if GetForegroundWindow is 0
        if not hwnd or not u32.IsWindowVisible(hwnd):
            desktop = u32.GetDesktopWindow()
            current = u32.GetTopWindow(desktop)
            while current:
                if u32.IsWindowVisible(current):
                    length = u32.GetWindowTextLengthW(current)
                    if length > 0:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        u32.GetWindowTextW(current, buf, length + 1)
                        title = buf.value
                        if title and not title.startswith("GDI+") and title != "Program Manager":
                            hwnd = current
                            break
                current = u32.GetWindow(current, 2)  # GW_HWNDNEXT

        if not hwnd:
            return WindowContext(
                hwnd=0,
                process_id=0,
                app_name="unknown",
                window_title="Unknown",
                url=None,
                bounding_box=None,
                is_browser=False,
            )

        # 1. Window Title
        length = u32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            u32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
        else:
            title = ""

        # 2. Process Name
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        app_name = "unknown"
        if pid.value:
            try:
                proc = psutil.Process(pid.value)
                app_name = proc.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                app_name = "unknown"

        # 3. Bounding box
        bbox = None
        try:
            rect = wintypes.RECT()
            if u32.GetWindowRect(hwnd, ctypes.byref(rect)):
                bbox = (rect.left, rect.top, rect.right, rect.bottom)
        except Exception:
            pass

        is_browser = app_name.lower() in BROWSER_PROCESSES
        url = None
        if is_browser:
            url = self._extract_browser_url(hwnd, app_name, title)

        return WindowContext(
            hwnd=hwnd,
            process_id=pid.value,
            app_name=app_name,
            window_title=title,
            url=url,
            bounding_box=bbox,
            is_browser=is_browser,
        )

    def get_active_context(self) -> WindowContext:
        """
        Extract active application name, window title, process ID, and URL (if browser).
        Dispatches to worker thread to ensure attachment to interactive desktop.
        """
        try:
            future = self._executor.submit(self._get_active_context_worker)
            return future.result(timeout=3.0)
        except Exception as e:
            logger.debug("Context extraction error: %s", e)
            return WindowContext(
                hwnd=0,
                process_id=0,
                app_name="unknown",
                window_title="Unknown",
                url=None,
                bounding_box=None,
                is_browser=False,
            )

    def _extract_browser_url(self, hwnd: int, app_name: str, title: str) -> Optional[str]:
        """
        Extract current URL from Chromium or Firefox address bar using Windows UI Automation.
        Caches URL for the same window to reduce CPU overhead.
        """
        now = time.time()
        if self._last_hwnd == hwnd and self._last_title == title and (now - self._last_url_time) < 0.5:
            return self._last_url

        try:
            import comtypes
            comtypes.CoInitialize()

            import uiautomation as auto
            auto.uiautomation.TIME_OUT_SECOND = self.uia_timeout

            ctrl = auto.ControlFromHandle(hwnd)
            if not ctrl:
                return None

            edit = ctrl.EditControl(searchDepth=10)
            val = None

            if edit.Exists(self.uia_timeout):
                try:
                    vp = edit.GetValuePattern()
                    if vp and vp.Value:
                        val = vp.Value
                except Exception:
                    pass

                if not val:
                    try:
                        lp = edit.GetLegacyIAccessiblePattern()
                        if lp and lp.Value:
                            val = lp.Value
                    except Exception:
                        pass

            if val:
                val = val.strip()
                if val and not (val.startswith("http://") or val.startswith("https://") or val.startswith("about:") or val.startswith("chrome://") or val.startswith("edge://") or val.startswith("brave://")):
                    if "." in val and " " not in val:
                        val = f"https://{val}"

                self._last_hwnd = hwnd
                self._last_title = title
                self._last_url = val
                self._last_url_time = now
                return val

        except Exception as e:
            logger.debug("Failed to extract URL from browser %s: %s", app_name, e)

        return None

    def close(self) -> None:
        """Release context thread pool."""
        self._executor.shutdown(wait=False, cancel_futures=True)
