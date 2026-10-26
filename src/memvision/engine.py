"""
Continuous Capture & Store Engine for mem-vision-mcp.
Orchestrates screen sampling, change detection, context extraction, privacy filtering, OCR, and storage.
"""

from __future__ import annotations

import logging
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from memvision.capture import ScreenCapturer
from memvision.change_detector import ChangeDetector
from memvision.config import AppConfig
from memvision.context import ContextExtractor, WindowContext, VisibleWindow
from memvision.ocr import LocalOCREngine
from memvision.privacy import PrivacyGatekeeper
from memvision.storage import CaptureRecord, MemoryStorage

logger = logging.getLogger(__name__)


class CaptureEngine:
    """
    Continuous background loop for desktop memory capture.
    Guarantees privacy-first gating and low CPU/memory footprint.
    """

    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config or AppConfig()
        self.capturer = ScreenCapturer(
            ocr_max_dimension=self.config.capture.ocr_max_dimension,
            storage_max_dimension=self.config.capture.storage_max_dimension,
            image_format=self.config.capture.image_format,
            image_quality=self.config.capture.image_quality,
            monitor_mode=self.config.capture.monitor_mode,
        )
        self.change_detector = ChangeDetector(
            threshold=self.config.capture.hash_threshold,
            algorithm=self.config.capture.hash_algorithm,
        )
        self.context_extractor = ContextExtractor()
        self.privacy_gate = PrivacyGatekeeper(
            config_path=self.config.privacy.config_path,
            enabled=self.config.privacy.enabled,
        )
        self.ocr_engine = LocalOCREngine(
            primary_engine=self.config.ocr.primary_engine,
            fallback_engine=self.config.ocr.fallback_engine,
            enabled=self.config.ocr.enabled,
        )
        self.storage = MemoryStorage(
            db_path=self.config.storage.database_path,
            enable_fts=self.config.storage.enable_fts,
        )
        self.screenshots_dir = Path(self.config.storage.screenshots_dir)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        self._running = False
        self._step_callbacks: list[Callable[[CaptureRecord], None]] = []

    def register_step_callback(self, cb: Callable[[CaptureRecord], None]) -> None:
        """Register a callback invoked whenever a capture is committed."""
        self._step_callbacks.append(cb)

    def capture_once(self, force: bool = False) -> Optional[CaptureRecord]:
        """
        Executes a single capture tick.
        Useful for on-demand captures, unit testing, and CLI dry-runs.
        Implements Approach 1: Spatial Window Masking ("The Blackout Curtain").
        """
        # 1. Grab screen in 100% full native resolution
        try:
            img = self.capturer.capture()
        except Exception as e:
            logger.error("Screen capture failed: %s", e)
            return None

        # 2. Extract active foreground window and visible top-level windows
        ctx: WindowContext = self.context_extractor.get_active_context()
        visible_windows: list[VisibleWindow] = self.context_extractor.get_visible_windows()

        # 3. Detect visible windows violating privacy rules
        blocked_windows = self.privacy_gate.filter_blocked_windows(visible_windows)
        active_decision = self.privacy_gate.evaluate(
            app_name=ctx.app_name,
            window_title=ctx.window_title,
            url=ctx.url,
        )

        masked_names: list[str] = []

        # 4. Handle Privacy Gating Decisions
        if not active_decision.is_allowed:
            # Active foreground window is restricted
            # Check window coverage to differentiate full-screen vs split-screen / windowed mode
            img_area = max(1, img.width * img.height)
            win_ratio = 1.0
            if ctx.bounding_box:
                l, t, r, b = ctx.bounding_box
                win_area = max(0, r - l) * max(0, b - t)
                win_ratio = min(1.0, win_area / img_area)

            # Check if there are other visible windows that are allowed
            allowed_windows = [
                w for w in visible_windows
                if self.privacy_gate.evaluate(w.app_name, w.window_title).is_allowed
            ]

            # If the restricted app covers >= 85% of screen or no allowed windows are visible, drop or redact stub
            if win_ratio >= 0.85 or not allowed_windows:
                if active_decision.action == "drop":
                    logger.info(
                        "🔒 PRIVACY DROP: Ignored capture for [%s] (Rule: %s, Reason: %s)",
                        ctx.app_name, active_decision.matched_rule, active_decision.reason
                    )
                    return None
                elif active_decision.action == "redact":
                    logger.info(
                        "🔒 PRIVACY REDACT: Saving sanitized stub for [%s] (Reason: %s)",
                        ctx.app_name, active_decision.reason
                    )
                    now_iso = datetime.now(timezone.utc).isoformat()
                    record = CaptureRecord(
                        timestamp=now_iso,
                        app_name=ctx.app_name,
                        window_title="[REDACTED]",
                        url=None,
                        ocr_text="[REDACTED BY PRIVACY GATEKEEPER]",
                        screenshot_path=None,
                        phash="",
                        width=img.width,
                        height=img.height,
                        is_redacted=1,
                        metadata={"reason": active_decision.reason, "rule": active_decision.matched_rule},
                    )
                    record_id = self.storage.save_capture(record)
                    record.id = record_id
                    return record
            else:
                # SPATIAL RESCUE (Split-Screen / Windowed Mode):
                # Active window is restricted (e.g. Discord), but work windows (e.g. VS Code) are visible side-by-side!
                topmost_allowed = allowed_windows[0]
                original_active = ctx.app_name
                ctx = WindowContext(
                    hwnd=topmost_allowed.hwnd,
                    process_id=topmost_allowed.process_id,
                    app_name=topmost_allowed.app_name,
                    window_title=topmost_allowed.window_title,
                    url=None,
                    bounding_box=topmost_allowed.bounding_box,
                    is_browser=topmost_allowed.app_name.lower() in ("chrome.exe", "msedge.exe", "brave.exe", "firefox.exe"),
                )
                logger.info(
                    "🔒 SPATIAL RESCUE: Active [%s] is blocked, but [%s] is visible. Masking [%s] and preserving [%s]!",
                    original_active, ctx.app_name, original_active, ctx.app_name
                )

        # 5. Apply Spatial Window Masking (The "Blackout Curtain")
        # Paint opaque solid black over all blocked window rectangles before OCR runs
        if blocked_windows:
            img, masked_count = self.capturer.redact_blocked_windows(img, blocked_windows, stamp_badge=False)
            masked_names = [getattr(w, "app_name", "Unknown") for w, _ in blocked_windows]
            logger.debug(
                "🔒 SPATIAL PRIVACY: Masked %d restricted window(s) (%s) on screen.",
                masked_count, ", ".join(set(masked_names))
            )

        # 6. Check for visual change on the masked image
        has_changed, distance, hash_str = self.change_detector.evaluate_change(img)
        if not has_changed and not force:
            logger.debug(
                "Tick: No visual change detected (dist=%d <= thresh=%d)",
                distance, self.config.capture.hash_threshold
            )
            return None

        # 7. Extract OCR text directly from 100% full-resolution image
        # Masked regions are pure black pixels, guaranteeing 0 OCR characters leaked
        ocr_start = time.perf_counter()
        ocr_text = self.ocr_engine.extract_text(img)
        ocr_duration_ms = (time.perf_counter() - ocr_start) * 1000

        # 8. Save preview image to disk
        # If any windows were masked, stamp sleek privacy badge on the saved preview
        now = datetime.now(timezone.utc)
        ts_slug = now.strftime("%Y%m%d_%H%M%S_%f")[:19]
        fmt_ext = "jpg" if self.config.capture.image_format.lower() in ("jpg", "jpeg") else "webp"
        filename = f"{ts_slug}_{hash_str[:8]}.{fmt_ext}"
        screenshot_file = self.screenshots_dir / filename

        preview_img = img
        if blocked_windows:
            preview_img = img.copy()
            self.capturer.redact_blocked_windows(preview_img, blocked_windows, stamp_badge=True)

        saved_path, thumb_w, thumb_h = self.capturer.save_image(preview_img, screenshot_file, downscale_for_storage=True)

        # 9. Persist to SQLite & FTS5
        record = CaptureRecord(
            timestamp=now.isoformat(),
            app_name=ctx.app_name,
            window_title=ctx.window_title,
            url=ctx.url,
            ocr_text=ocr_text,
            screenshot_path=saved_path,
            phash=hash_str,
            width=img.width,
            height=img.height,
            is_redacted=1 if (blocked_windows and not ocr_text.strip()) else 0,
            metadata={
                "change_distance": distance,
                "ocr_duration_ms": round(ocr_duration_ms, 2),
                "process_id": ctx.process_id,
                "native_dimensions": f"{img.width}x{img.height}",
                "storage_dimensions": f"{thumb_w}x{thumb_h}",
                "spatial_masked_windows": list(set(masked_names)),
                "is_spatially_masked": bool(blocked_windows),
            },
        )
        record_id = self.storage.save_capture(record)
        record.id = record_id

        logger.info(
            "📸 CAPTURE #%d: App='%s' | Title='%.40s...' | URL=%s | OCR=%d chars (%.1fms)%s",
            record_id,
            ctx.app_name,
            ctx.window_title,
            ctx.url or "None",
            len(ocr_text),
            ocr_duration_ms,
            f" [MASKED: {', '.join(set(masked_names))}]" if masked_names else "",
        )

        for cb in self._step_callbacks:
            try:
                cb(record)
            except Exception as e:
                logger.error("Error in capture callback: %s", e)

        return record

    def run(self) -> None:
        """Starts the continuous background capture loop."""
        self._running = True
        interval = max(0.2, self.config.capture.interval_seconds)

        def _sig_handler(sig, frame):
            logger.info("Termination signal received. Stopping capture engine gracefully...")
            self.stop()

        signal.signal(signal.SIGINT, _sig_handler)
        signal.signal(signal.SIGTERM, _sig_handler)

        logger.info("mem-vision-mcp capture engine started. Polling every %.1fs (hash threshold=%d)...",
                    interval, self.config.capture.hash_threshold)

        try:
            while self._running:
                t0 = time.time()
                try:
                    self.capture_once()
                except Exception as e:
                    logger.error("Error during capture loop tick: %s", e, exc_info=True)

                elapsed = time.time() - t0
                sleep_time = max(0.05, interval - elapsed)
                time.sleep(sleep_time)

        finally:
            self.stop()
            logger.info("mem-vision-mcp capture engine stopped.")

    def stop(self) -> None:
        """Stops the capture loop and releases resources."""
        self._running = False
        self.capturer.close()
