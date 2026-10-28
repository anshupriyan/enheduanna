"""
Windows Window Context and Browser URL Extractor for mem-vision-mcp.
Extracts active foreground window, process name, window title, and active browser tab URLs via UI Automation.
"""

from __future__ import annotations

import concurrent.futures
import ctypes
from ctypes import wintypes
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import time
from dataclasses import dataclass
from typing import Optional, Tuple
import urllib.parse
import psutil

logger = logging.getLogger(__name__)

_project_root = Path(__file__).resolve().parent.parent.parent

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

# Known IDE and text editor process names
IDE_PROCESSES = {
    "code.exe",
    "cursor.exe",
    "windsurf.exe",
    "vscodium.exe",
    "antigravity ide.exe",
    "positron.exe",
    "devenv.exe",
    "pycharm64.exe",
    "idea64.exe",
    "webstorm64.exe",
    "clion64.exe",
    "rider64.exe",
    "sublime_text.exe",
    "notepad++.exe",
    "notepad.exe",
    "windowsterminal.exe",
}


def enable_dpi_awareness_v2() -> bool:
    """Enables Per-Monitor DPI Awareness v2 for exact multi-monitor coordinates."""
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        res = ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        if res:
            return True
    except Exception:
        pass
    try:
        res = ctypes.windll.shcore.SetProcessDpiAwareness(2)
        if res == 0:
            return True
    except Exception:
        pass
    try:
        return bool(ctypes.windll.user32.SetProcessDPIAware())
    except Exception:
        return False

# Enable on module import
enable_dpi_awareness_v2()


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


def _init_context_thread() -> bool:
    """Attaches worker thread to interactive desktop WinSta0\\default."""
    enable_dpi_awareness_v2()
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
    file_path: Optional[str] = None
    workspace_path: Optional[str] = None
    is_ide: bool = False


@dataclass
class VisibleWindow:
    """Represents a visible desktop window with spatial coordinates and Z-order metadata."""
    hwnd: int
    process_id: int
    app_name: str
    window_title: str
    bounding_box: Tuple[int, int, int, int]  # (left, top, right, bottom) in virtual screen coordinates
    url: Optional[str] = None
    z_index: int = 0
    is_foreground: bool = False
    monitor: str = "Primary"
    visible_fraction: float = 1.0
    is_browser: bool = False


class ContextExtractor:
    """
    Extracts rich desktop context from the active foreground window
    and visible top-level windows for spatial privacy masking.
    Uses Win32 APIs and UI Automation for browser URL extraction.
    """

    def __init__(self, uia_timeout_seconds: float = 0.5):
        self.uia_timeout = uia_timeout_seconds
        self._last_hwnd: Optional[int] = None
        self._last_title: Optional[str] = None
        self._last_url: Optional[str] = None
        self._last_url_time: float = 0.0
        self._pid_name_cache: dict[int, Tuple[str, float]] = {}
        self._file_path_cache: dict[Tuple[int, str], Tuple[Optional[str], Optional[str], float]] = {}
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

        app_name_lower = app_name.lower()
        is_ide = (
            app_name_lower in IDE_PROCESSES
            or any(k in app_name_lower for k in ("code", "cursor", "studio", "pycharm", "idea", "sublime", "notepad"))
        )

        file_path: Optional[str] = None
        workspace_path: Optional[str] = None
        has_file_extension = bool(title and any(ext in title.lower() for ext in (
            ".py", ".md", ".json", ".js", ".ts", ".html", ".css", ".txt", ".rs",
            ".go", ".c", ".cpp", ".h", ".yaml", ".yml", ".toml", ".sql"
        )))

        if is_ide or has_file_extension:
            file_path, workspace_path = self.resolve_file_path(hwnd, pid.value, app_name, title)

        return WindowContext(
            hwnd=hwnd,
            process_id=pid.value,
            app_name=app_name,
            window_title=title,
            url=url,
            bounding_box=bbox,
            is_browser=is_browser,
            file_path=file_path,
            workspace_path=workspace_path,
            is_ide=is_ide,
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

    def _get_process_name(self, pid: int) -> str:
        """Cached lookup of process name by PID with a 5-second TTL."""
        if not pid:
            return "unknown"
        now = time.time()
        cached = self._pid_name_cache.get(pid)
        if cached and (now - cached[1]) < 5.0:
            return cached[0]
        try:
            name = psutil.Process(pid).name()
        except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
            name = "unknown"
        self._pid_name_cache[pid] = (name, now)
        return name

    def _get_visible_windows_worker(self) -> list[VisibleWindow]:
        """
        Enumerates all visible, uncloaked, non-minimized desktop windows in Z-order.
        Uses DWMWA_EXTENDED_FRAME_BOUNDS, DPI awareness v2, and virtual-screen coordinates.
        Executes on the worker thread attached to the interactive desktop.
        """
        u32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        dwmapi = getattr(ctypes.windll, "dwmapi", None)
        DWMWA_EXTENDED_FRAME_BOUNDS = 9
        DWMWA_CLOAKED = 14
        WS_EX_TOOLWINDOW = 0x00000080
        GWL_EXSTYLE = -20

        # Retrieve thread desktop handle
        tid = kernel32.GetCurrentThreadId()
        u32.GetThreadDesktop.restype = wintypes.HANDLE
        u32.GetThreadDesktop.argtypes = [wintypes.DWORD]
        hdesk = u32.GetThreadDesktop(tid)

        foreground_hwnd = u32.GetForegroundWindow()
        own_pid = os.getpid()
        windows: list[VisibleWindow] = []

        def enum_handler(hwnd: int, lparam: int) -> bool:
            try:
                # 1. Must be visible and not minimized
                if not u32.IsWindowVisible(hwnd) or u32.IsIconic(hwnd):
                    return True

                # 2. Check cloaking (virtual desktops, suspended background apps)
                if dwmapi:
                    cloaked = wintypes.DWORD()
                    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0:
                        if cloaked.value != 0:
                            return True

                # 3. Skip tool windows
                ex_style = u32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                if ex_style & WS_EX_TOOLWINDOW:
                    return True

                # 4. Geometry check using DWMWA_EXTENDED_FRAME_BOUNDS for exact window bounds
                rect = wintypes.RECT()
                has_bounds = False
                if dwmapi:
                    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect)) == 0:
                        has_bounds = True
                if not has_bounds:
                    if not u32.GetWindowRect(hwnd, ctypes.byref(rect)):
                        return True

                width = rect.right - rect.left
                height = rect.bottom - rect.top
                if width <= 30 or height <= 30:
                    return True

                # 5. Process Name
                pid = wintypes.DWORD()
                u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                proc_name = self._get_process_name(pid.value)

                # 6. Window Title
                length = u32.GetWindowTextLengthW(hwnd)
                title = ""
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    u32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value

                # 7. Class name check for Shell / System artifacts
                class_buf = ctypes.create_unicode_buffer(256)
                u32.GetClassNameW(hwnd, class_buf, 256)
                class_name = class_buf.value

                if class_name in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW", "Windows.UI.Core.CoreWindow"):
                    return True
                if title == "Program Manager" or proc_name in ("dwm.exe",):
                    return True
                if not title and proc_name in ("explorer.exe", "dwm.exe", "svchost.exe", "unknown"):
                    return True

                # Skip Enheduanna capture process itself
                if pid.value == own_pid:
                    return True

                # 8. Monitor detection
                monitor_name = "Primary"
                hmon = u32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
                if hmon:
                    mon_info = MONITORINFOEXW()
                    mon_info.cbSize = ctypes.sizeof(MONITORINFOEXW)
                    if u32.GetMonitorInfoW(hmon, ctypes.byref(mon_info)):
                        dev_name = mon_info.szDevice
                        is_pri = bool(mon_info.dwFlags & 1)
                        monitor_name = f"{dev_name} (Primary)" if is_pri else dev_name

                is_fg = (hwnd == foreground_hwnd)
                is_br = proc_name.lower() in BROWSER_PROCESSES

                # URL extraction
                url = None
                if is_br:
                    if is_fg and self._last_url and (time.time() - self._last_url_time) < 15.0:
                        url = self._last_url
                    else:
                        url = self._extract_browser_url(hwnd, proc_name, title)

                windows.append(
                    VisibleWindow(
                        hwnd=hwnd,
                        process_id=pid.value,
                        app_name=proc_name,
                        window_title=title,
                        bounding_box=(rect.left, rect.top, rect.right, rect.bottom),
                        url=url,
                        z_index=len(windows),
                        is_foreground=is_fg,
                        monitor=monitor_name,
                        visible_fraction=1.0,
                        is_browser=is_br,
                    )
                )
            except Exception as e:
                logger.debug("Error inspecting window %s: %s", hwnd, e)
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        cb = WNDENUMPROC(enum_handler)
        if hdesk:
            u32.EnumDesktopWindows(hdesk, cb, 0)
        else:
            u32.EnumWindows(cb, 0)

        return windows

    def get_visible_windows(self) -> list[VisibleWindow]:
        """
        Retrieves all visible top-level windows with their spatial coordinates in Z-order.
        Dispatches to worker thread to ensure attachment to interactive desktop.
        """
        try:
            future = self._executor.submit(self._get_visible_windows_worker)
            return future.result(timeout=2.0)
        except Exception as e:
            logger.debug("Visible windows extraction error: %s", e)
            return []

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

    def resolve_file_path(
        self, hwnd: int, pid: int, app_name: str, title: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Extracts and resolves the exact absolute file path and workspace path
        for files open in IDEs and text editors.
        Disambiguates duplicate filenames (e.g. README.md or config.json)
        by inspecting UI Automation, IDE workspace storage, or resolving within
        the active project folder.

        Returns:
            (resolved_file_path, workspace_path)
        """
        if not title:
            return None, None

        now = time.time()
        cache_key = (pid, title)
        cached = self._file_path_cache.get(cache_key)
        if cached and (now - cached[2]) < 2.0:
            return cached[0], cached[1]

        resolved_file: Optional[str] = None
        resolved_ws: Optional[str] = None

        try:
            resolved_file, resolved_ws = self._do_resolve_file_path(hwnd, pid, app_name, title)
        except Exception as e:
            logger.debug("Path resolution error for [%s] '%s': %s", app_name, title, e)

        self._file_path_cache[cache_key] = (resolved_file, resolved_ws, now)
        return resolved_file, resolved_ws

    def _do_resolve_file_path(
        self, hwnd: int, pid: int, app_name: str, title: str
    ) -> Tuple[Optional[str], Optional[str]]:
        clean_title = title.strip()

        # Tier 1: Check for explicit absolute path in title (e.g. Notepad, Notepad++, custom IDE window.title)
        m_win = re.search(r"([a-zA-Z]:[\\/][^\*\?\<\>\|\:\"]+?\.[a-zA-Z0-9_\-]+)", clean_title)
        if m_win:
            candidate = Path(m_win.group(1).strip())
            if candidate.is_file():
                return str(candidate.resolve()), str(candidate.parent.resolve())

        # Tier 2: Extract candidate filename and workspace name from window title
        candidate_filename: Optional[str] = None
        workspace_hint: Optional[str] = None

        # Pattern A: Antigravity IDE / VS Code variant: "memvison - Antigravity IDE - README.md"
        m_anti = re.search(
            r"^(?P<workspace>[^-\u2013\u2014]+?)\s*[-\u2013\u2014]\s*(?:Antigravity IDE|Visual Studio Code|Cursor|Windsurf|Code|VSCodium)\s*[-\u2013\u2014]\s*(?P<filename>[^-\u2013\u2014]+)$",
            clean_title,
            re.IGNORECASE,
        )
        if m_anti:
            workspace_hint = m_anti.group("workspace").strip()
            candidate_filename = m_anti.group("filename").strip().lstrip("●* ")

        # Pattern B: Standard VS Code / Cursor: "● README.md - memvison - Visual Studio Code"
        if not candidate_filename:
            m_vsc = re.search(
                r"^●?\s*\*?\s*(?P<filename>[^-\u2013\u2014]+?)\s*[-\u2013\u2014]\s*(?P<workspace>[^-\u2013\u2014]+?)\s*[-\u2013\u2014]\s*(?:Visual Studio Code|Cursor|Antigravity IDE|Windsurf|Code|VSCodium)",
                clean_title,
                re.IGNORECASE,
            )
            if m_vsc:
                candidate_filename = m_vsc.group("filename").strip().lstrip("●* ")
                workspace_hint = m_vsc.group("workspace").strip()

        # Pattern C: VS Code WSL / remote: "README.md - memvison [WSL: Ubuntu] - Visual Studio Code"
        if not candidate_filename:
            m_wsl = re.search(
                r"^●?\s*\*?\s*(?P<filename>[^-\u2013\u2014]+?)\s*[-\u2013\u2014]\s*(?P<workspace>[^-\u2013\u2014\[]+?)\s*\[.*?\]\s*[-\u2013\u2014]",
                clean_title,
            )
            if m_wsl:
                candidate_filename = m_wsl.group("filename").strip().lstrip("●* ")
                workspace_hint = m_wsl.group("workspace").strip()

        # Pattern D: Sublime Text: "README.md (memvison) - Sublime Text"
        if not candidate_filename:
            m_sub = re.search(
                r"^(?P<filename>[^-\u2013\u2014\(\)]+?)\s*\((?P<workspace>[^\)]+)\)\s*-\s*Sublime Text",
                clean_title,
                re.IGNORECASE,
            )
            if m_sub:
                candidate_filename = m_sub.group("filename").strip().lstrip("●* ")
                workspace_hint = m_sub.group("workspace").strip()

        # Pattern E: JetBrains (PyCharm / IntelliJ): "[memvison] - README.md" or "memvison – README.md"
        if not candidate_filename:
            m_jb = re.search(
                r"^\[(?P<workspace>[^\]]+)\]\s*[-\u2013\u2014]\s*(?P<filename>.+)",
                clean_title,
            )
            if m_jb:
                workspace_hint = m_jb.group("workspace").strip()
                candidate_filename = m_jb.group("filename").strip().lstrip("●* ")

        # Pattern F: Notepad / simple editor: "*README.md - Notepad"
        if not candidate_filename:
            m_np = re.search(r"^\*?(?P<filename>[^-\u2013\u2014]+?)\s*-\s*Notepad", clean_title, re.IGNORECASE)
            if m_np:
                candidate_filename = m_np.group("filename").strip().lstrip("●* ")

        # Pattern G: Fallback split by dash delimiters
        if not candidate_filename:
            parts = [p.strip() for p in re.split(r"[-–—]", clean_title) if p.strip()]
            for p in parts:
                clean_p = p.lstrip("●* ")
                if "." in clean_p and not any(clean_p.lower().endswith(x) for x in (".exe", ".com", ".app")):
                    candidate_filename = clean_p
                    break
            for p in parts:
                p_clean = p.strip()
                if p_clean != candidate_filename and not any(app in p_clean.lower() for app in ("visual studio", "code", "cursor", "antigravity", "windsurf", "notepad", "sublime")):
                    workspace_hint = p_clean
                    break

        # Tier 3: UI Automation Inspection (e.g. active tab tooltip or breadcrumb bar)
        if hwnd:
            try:
                import comtypes
                comtypes.CoInitialize()
                import uiautomation as auto

                ctrl = auto.ControlFromHandle(hwnd)
                if ctrl:
                    tabs = ctrl.GetChildren()
                    for child in tabs[:15]:
                        help_text = getattr(child, "HelpText", "") or ""
                        if help_text:
                            p_cand = Path(help_text.strip())
                            if p_cand.is_file():
                                return str(p_cand.resolve()), str(p_cand.parent.resolve())
            except Exception:
                pass

        # Tier 4: IDE Process Workspace Storage (VS Code / Cursor / Windsurf / Antigravity IDE)
        vsc_workspace_dir: Optional[Path] = None
        if pid:
            try:
                proc = psutil.Process(pid)
                for ofile in proc.open_files():
                    if "workspaceStorage" in ofile.path and ofile.path.endswith("state.vscdb"):
                        vscdb_path = Path(ofile.path)
                        ws_json_path = vscdb_path.parent / "workspace.json"
                        if ws_json_path.is_file():
                            try:
                                ws_info = json.loads(ws_json_path.read_text(encoding="utf-8"))
                                folder_uri = ws_info.get("folder", "")
                                if folder_uri:
                                    parsed_uri = urllib.parse.urlparse(folder_uri)
                                    raw_path = urllib.parse.unquote(parsed_uri.path).lstrip("/")
                                    if len(raw_path) >= 2 and raw_path[1] == ":":
                                        p_ws = Path(raw_path)
                                    else:
                                        p_ws = Path("/" + raw_path)
                                    if p_ws.is_dir():
                                        vsc_workspace_dir = p_ws
                            except Exception:
                                pass

                        if candidate_filename and vscdb_path.is_file():
                            try:
                                conn = sqlite3.connect(str(vscdb_path), timeout=0.2)
                                row = conn.cursor().execute(
                                    "SELECT value FROM ItemTable WHERE key = 'history.entries';"
                                ).fetchone()
                                conn.close()
                                if row:
                                    entries = json.loads(row[0])
                                    for entry in entries:
                                        res_uri = entry.get("editor", {}).get("resource", "")
                                        if res_uri:
                                            p_parsed = urllib.parse.urlparse(res_uri)
                                            unquoted = urllib.parse.unquote(p_parsed.path).lstrip("/")
                                            cand_path = Path(unquoted)
                                            if cand_path.name.lower() == candidate_filename.lower() and cand_path.is_file():
                                                ws_res = str(vsc_workspace_dir.resolve()) if vsc_workspace_dir else str(cand_path.parent.resolve())
                                                return str(cand_path.resolve()), ws_res
                            except Exception:
                                pass
            except Exception:
                pass

        # Tier 5: Project Folder Resolution & Disambiguation
        if not candidate_filename:
            return None, None

        target_ws_dir: Optional[Path] = vsc_workspace_dir
        if not target_ws_dir and workspace_hint:
            if _project_root.name.lower() == workspace_hint.lower():
                target_ws_dir = _project_root
            elif _project_root.parent.name.lower() == workspace_hint.lower():
                target_ws_dir = _project_root.parent
            elif (_project_root.parent / workspace_hint).is_dir():
                target_ws_dir = _project_root.parent / workspace_hint
            elif (Path.cwd().parent / workspace_hint).is_dir():
                target_ws_dir = Path.cwd().parent / workspace_hint
            elif (Path.cwd() / workspace_hint).is_dir():
                target_ws_dir = Path.cwd() / workspace_hint

        if not target_ws_dir:
            target_ws_dir = _project_root

        # 1. Direct root file check
        direct_file = target_ws_dir / candidate_filename
        if direct_file.is_file():
            return str(direct_file.resolve()), str(target_ws_dir.resolve())

        # 2. Search workspace recursively, ignoring cache/vendor/virtualenv directories
        ignored_dirs = {".git", ".venv", "venv", ".pytest_cache", "node_modules", "__pycache__", ".idea", ".vscode", "dist", "build"}
        matching_files: list[Path] = []
        try:
            for root, dirs, files in os.walk(target_ws_dir):
                dirs[:] = [d for d in dirs if d not in ignored_dirs]
                for f in files:
                    if f.lower() == candidate_filename.lower():
                        matching_files.append(Path(root) / f)
                        if len(matching_files) >= 10:
                            break
                if len(matching_files) >= 10:
                    break
        except Exception:
            pass

        if len(matching_files) == 1:
            return str(matching_files[0].resolve()), str(target_ws_dir.resolve())
        elif len(matching_files) > 1:
            def _file_score(p: Path) -> float:
                score = 0.0
                p_str = str(p).lower()
                if "test" not in p_str and "cache" not in p_str:
                    score += 1000.0
                try:
                    score += p.stat().st_mtime
                except Exception:
                    pass
                return score

            best = max(matching_files, key=_file_score)
            return str(best.resolve()), str(target_ws_dir.resolve())

        return None, str(target_ws_dir.resolve()) if target_ws_dir else None

    def close(self) -> None:
        """Release context thread pool."""
        self._executor.shutdown(wait=False, cancel_futures=True)

