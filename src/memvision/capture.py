"""
High-performance screen capture engine for Windows.
Uses a dedicated worker thread with WinSta0\\default desktop attachment and mss for fast GDI/DirectX capture.
"""

from __future__ import annotations

import concurrent.futures
import ctypes
from ctypes import wintypes
import io
import logging
from pathlib import Path
from typing import Optional, Tuple
import mss
from PIL import Image, ImageGrab

logger = logging.getLogger(__name__)


def _init_capture_thread() -> bool:
    """
    Attaches the dedicated capture worker thread to interactive desktop WinSta0\\default.
    Must be called on a clean thread before any GUI handles are created.
    """
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
        logger.debug("Desktop station attachment failed on worker thread: %s", e)
    return False


class ScreenCapturer:
    """
    Captures screenshots efficiently on Windows using a dedicated capture thread.
    Optimized for continuous background loops with low CPU and memory overhead.
    """

    def __init__(
        self,
        max_dimension: int = 1920,
        image_format: str = "jpeg",
        image_quality: int = 80,
    ):
        self.max_dimension = max_dimension
        self.image_format = image_format.lower()
        self.image_quality = image_quality
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="memvision_capturer",
            initializer=_init_capture_thread,
        )

    def _grab_worker(self, bounding_box: Optional[Tuple[int, int, int, int]] = None) -> Image.Image:
        """Executed inside dedicated capture worker thread."""
        try:
            with mss.MSS() as sct:
                if bounding_box:
                    left, top, right, bottom = bounding_box
                    monitor = {
                        "left": left,
                        "top": top,
                        "width": max(1, right - left),
                        "height": max(1, bottom - top),
                    }
                else:
                    monitor = sct.monitors[0]

                sct_img = sct.grab(monitor)
                return Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        except Exception as err:
            logger.debug("mss grab failed in worker (%s); trying ImageGrab fallback", err)
            if bounding_box:
                img = ImageGrab.grab(bbox=bounding_box, all_screens=True)
            else:
                img = ImageGrab.grab(all_screens=True)
            return img.convert("RGB")

    def capture(self, bounding_box: Optional[Tuple[int, int, int, int]] = None) -> Image.Image:
        """
        Capture the screen or a specific bounding box (left, top, right, bottom).
        Returns a PIL Image in RGB format.
        """
        try:
            future = self._executor.submit(self._grab_worker, bounding_box)
            raw_img = future.result(timeout=5.0)
            return self._resize_if_needed(raw_img)
        except Exception as e:
            logger.error("Screen capture failed: %s", e)
            raise RuntimeError(f"Unable to capture screen: {e}") from e

    def _resize_if_needed(self, img: Image.Image) -> Image.Image:
        """Downscale image if dimensions exceed max_dimension, preserving aspect ratio."""
        width, height = img.size
        max_dim = max(width, height)
        if self.max_dimension > 0 and max_dim > self.max_dimension:
            scale = self.max_dimension / float(max_dim)
            new_w = max(1, int(width * scale))
            new_h = max(1, int(height * scale))
            return img.resize((new_w, new_h), Image.Resampling.BOX)
        return img

    def save_image(self, img: Image.Image, output_path: str | Path) -> str:
        """Save a PIL Image to disk using configured format and compression quality."""
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        fmt = "JPEG" if self.image_format in ("jpg", "jpeg") else "WEBP"
        params = {"quality": self.image_quality}
        if fmt == "JPEG":
            params["optimize"] = True

        img.save(out_path, format=fmt, **params)
        return str(out_path.resolve())

    def to_bytes(self, img: Image.Image) -> bytes:
        """Encode image to compressed bytes in-memory."""
        buf = io.BytesIO()
        fmt = "JPEG" if self.image_format in ("jpg", "jpeg") else "WEBP"
        img.save(buf, format=fmt, quality=self.image_quality)
        return buf.getvalue()

    def close(self) -> None:
        """Release capture thread pool resources."""
        self._executor.shutdown(wait=False, cancel_futures=True)
