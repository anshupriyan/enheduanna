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
from typing import Any, List, Optional, Tuple
import mss
from PIL import Image, ImageDraw, ImageFont, ImageGrab

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
        self.last_capture_origin: Tuple[int, int] = (0, 0)
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="memvision_capturer",
            initializer=_init_capture_thread,
        )

    def _grab_worker(self, bounding_box: Optional[Tuple[int, int, int, int]] = None) -> Tuple[Image.Image, Tuple[int, int]]:
        """Executed inside dedicated capture worker thread. Returns (image, (origin_x, origin_y))."""
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

                origin = (int(monitor.get("left", 0)), int(monitor.get("top", 0)))
                sct_img = sct.grab(monitor)
                return Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX"), origin
        except Exception as err:
            logger.debug("mss grab failed in worker (%s); trying ImageGrab fallback", err)
            ox, oy = 0, 0
            try:
                ox = ctypes.windll.user32.GetSystemMetrics(76)
                oy = ctypes.windll.user32.GetSystemMetrics(77)
            except Exception:
                pass
            if bounding_box:
                img = ImageGrab.grab(bbox=bounding_box, all_screens=True)
                origin = (bounding_box[0], bounding_box[1])
            else:
                img = ImageGrab.grab(all_screens=True)
                origin = (ox, oy)
            return img.convert("RGB"), origin

    def capture(self, bounding_box: Optional[Tuple[int, int, int, int]] = None) -> Image.Image:
        """
        Capture the screen in full native resolution for OCR.
        Returns a PIL Image in RGB format, caching last_capture_origin.
        """
        try:
            future = self._executor.submit(self._grab_worker, bounding_box)
            raw_img, origin = future.result(timeout=5.0)
            self.last_capture_origin = origin
            return self._resize_if_needed(raw_img, max_dim=self.ocr_max_dimension)
        except Exception as e:
            logger.error("Screen capture failed: %s", e)
            raise RuntimeError(f"Unable to capture screen: {e}") from e

    def redact_blocked_windows(
        self,
        img: Image.Image,
        blocked_windows: list[Tuple[Any, Any]],
        stamp_badge: bool = False,
    ) -> Tuple[Image.Image, int]:
        """
        Convenience wrapper to redact a list of (VisibleWindow, PrivacyDecision) tuples from img.
        Uses cached last_capture_origin to translate screen coordinates to image-local pixels.
        """
        regions = []
        for win, _ in blocked_windows:
            bbox = getattr(win, "bounding_box", None)
            if bbox:
                label = getattr(win, "app_name", "Blocked App")
                regions.append((bbox, label))
        return redact_regions(
            img,
            regions=regions,
            origin=self.last_capture_origin,
            stamp_badge=stamp_badge,
        )

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

        fmt = "JPEG" if self.image_format.lower() in ("jpg", "jpeg") else "WEBP"
        params = {"quality": self.image_quality}
        if fmt == "JPEG":
            params["optimize"] = True

        to_save.save(out_path, format=fmt, **params)
        return str(out_path.resolve()), to_save.width, to_save.height

    def to_bytes(self, img: Image.Image) -> bytes:
        """Encode image to compressed bytes in-memory."""
        buf = io.BytesIO()
        fmt = "JPEG" if self.image_format.lower() in ("jpg", "jpeg") else "WEBP"
        img.save(buf, format=fmt, quality=self.image_quality)
        return buf.getvalue()

    def close(self) -> None:
        """Release capture thread pool resources."""
        self._executor.shutdown(wait=False, cancel_futures=True)


def redact_regions(
    img: Image.Image,
    regions: List[Tuple[Tuple[int, int, int, int], str]],
    origin: Tuple[int, int] = (0, 0),
    fill_color: Tuple[int, int, int] = (16, 16, 20),
    stamp_badge: bool = False,
) -> Tuple[Image.Image, int]:
    """
    Paints an opaque blackout curtain over specified screen regions on an in-memory image.
    Guarantees that sensitive windows (e.g. Discord, password managers) cannot be read by OCR
    or stored in disk previews.

    Args:
        img: In-memory PIL Image.
        regions: List of ((screen_left, screen_top, screen_right, screen_bottom), label).
                 Bounding boxes are in virtual desktop coordinates.
        origin: (capture_origin_x, capture_origin_y) offset of the captured screenshot.
        fill_color: RGB tuple for the blackout rectangle (default dark charcoal).
        stamp_badge: If True, draws a sleek, centered privacy badge for preview visibility.
                     If False (default, for pre-OCR), leaves it pure solid black so OCR extracts 0 chars.

    Returns:
        (modified_image, count_redacted_regions)
    """
    if not regions:
        return img, 0

    draw = ImageDraw.Draw(img)
    redacted_count = 0
    img_w, img_h = img.size
    ox, oy = origin

    for (left, top, right, bottom), label in regions:
        # Convert virtual screen coordinates to image-local pixel coordinates
        x1 = max(0, min(img_w, left - ox))
        y1 = max(0, min(img_h, top - oy))
        x2 = max(0, min(img_w, right - ox))
        y2 = max(0, min(img_h, bottom - oy))

        rw = x2 - x1
        rh = y2 - y1

        # Skip if outside current capture or zero area
        if rw <= 10 or rh <= 10:
            continue

        # 1. Paint the solid blackout curtain
        draw.rectangle([x1, y1, x2, y2], fill=fill_color)
        redacted_count += 1

        # 2. If stamp_badge is True (for thumbnails / preview inspection), draw sleek badge
        if stamp_badge and rw >= 120 and rh >= 40:
            # Subtle accent border around the redacted window
            draw.rectangle([x1, y1, x2, y2], outline=(48, 50, 62), width=2)

            # Center badge
            cx = x1 + rw // 2
            cy = y1 + rh // 2
            badge_w = min(max(150, rw - 40), 280)
            badge_h = 44 if rh >= 90 else 26

            bx1 = cx - badge_w // 2
            by1 = cy - badge_h // 2
            bx2 = cx + badge_w // 2
            by2 = cy + badge_h // 2

            # Badge pill background & border
            draw.rectangle([bx1, by1, bx2, by2], fill=(24, 26, 34), outline=(80, 85, 105), width=1)

            font = ImageFont.load_default()
            header_text = "[ PRIVACY PROTECTED ]"
            draw.text((cx, by1 + (6 if badge_h > 30 else 6)), header_text, fill=(245, 180, 50), font=font, anchor="mt")

            if badge_h > 30 and label:
                sub_text = label[:32]
                draw.text((cx, by1 + 22), sub_text, fill=(180, 185, 195), font=font, anchor="mt")

    return img, redacted_count

