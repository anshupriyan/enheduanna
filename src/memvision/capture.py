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
        ocr_max_dimension: int = 0,
        storage_max_dimension: int = 1280,
        image_format: str = "jpeg",
        image_quality: int = 80,
        monitor_mode: str = "all",
        max_dimension: Optional[int] = None,
    ):
        if max_dimension is not None:
            ocr_max_dimension = max_dimension
        self.ocr_max_dimension = ocr_max_dimension
        self.storage_max_dimension = storage_max_dimension
        self.image_format = image_format.lower()
        self.image_quality = image_quality
        self.monitor_mode = monitor_mode.lower()
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
                elif self.monitor_mode == "primary":
                    # Look for primary monitor
                    primary_mon = None
                    for m in sct.monitors[1:]:
                        if m.get("is_primary"):
                            primary_mon = m
                            break
                    monitor = primary_mon or (sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0])
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
        Capture the screen in full native resolution for OCR.
        Returns a PIL Image in RGB format.
        """
        try:
            future = self._executor.submit(self._grab_worker, bounding_box)
            raw_img = future.result(timeout=5.0)
            return self._resize_if_needed(raw_img, max_dim=self.ocr_max_dimension)
        except Exception as e:
            logger.error("Screen capture failed: %s", e)
            raise RuntimeError(f"Unable to capture screen: {e}") from e

    def _resize_if_needed(self, img: Image.Image, max_dim: int = 0) -> Image.Image:
        """Preserves 100% full native resolution when max_dim <= 0."""
        if max_dim <= 0:
            return img

        width, height = img.size
        longest = max(width, height)
        if longest > max_dim:
            scale = max_dim / float(longest)
            new_w = max(1, int(width * scale))
            new_h = max(1, int(height * scale))
            return img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        return img

    def create_storage_thumbnail(self, img: Image.Image, max_dim: Optional[int] = None) -> Image.Image:
        """
        Downscales an in-memory image to a lightweight preview (e.g. 720p/1280px) for saving to disk.
        """
        target_dim = self.storage_max_dimension if max_dim is None else max_dim
        return self._resize_if_needed(img, max_dim=target_dim)

    def save_image(self, img: Image.Image, output_path: str | Path, downscale_for_storage: bool = True) -> Tuple[str, int, int]:
        """
        Downscales image to storage resolution, compresses, and saves to disk.
        Returns tuple of (saved_file_path, saved_width, saved_height).
        """
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        to_save = self.create_storage_thumbnail(img) if downscale_for_storage else img

        fmt = "JPEG" if self.image_format in ("jpg", "jpeg") else "WEBP"
        params = {"quality": self.image_quality}
        if fmt == "JPEG":
            params["optimize"] = True

        to_save.save(out_path, format=fmt, **params)
        return str(out_path.resolve()), to_save.width, to_save.height

    def to_bytes(self, img: Image.Image) -> bytes:
        """Encode image to compressed bytes in-memory."""
        buf = io.BytesIO()
        fmt = "JPEG" if self.image_format in ("jpg", "jpeg") else "WEBP"
        img.save(buf, format=fmt, quality=self.image_quality)
        return buf.getvalue()

    def close(self) -> None:
        """Release capture thread pool resources."""
        self._executor.shutdown(wait=False, cancel_futures=True)
