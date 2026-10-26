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
from memvision.context import ContextExtractor, WindowContext
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
            max_dimension=self.config.capture.max_dimension,
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
        """
        # 1. Grab screen
        try:
            img = self.capturer.capture()
        except Exception as e:
            logger.error("Screen capture failed: %s", e)
            return None

        # 2. Check for visual change
        has_changed, distance, hash_str = self.change_detector.evaluate_change(img)
        if not has_changed and not force:
            logger.debug("Tick: No visual change detected (dist=%d <= thresh=%d)", distance, self.config.capture.hash_threshold)
            return None

        # 3. Extract active window and browser context
        ctx: WindowContext = self.context_extractor.get_active_context()

        # 4. Privacy Gatekeeper check (Priority #1)
        decision = self.privacy_gate.evaluate(
            app_name=ctx.app_name,
            window_title=ctx.window_title,
            url=ctx.url,
        )

        if not decision.is_allowed:
            if decision.action == "drop":
                logger.info(
                    "🔒 PRIVACY DROP: Ignored capture for [%s] (Rule: %s, Reason: %s)",
                    ctx.app_name, decision.matched_rule, decision.reason
                )
                return None
            elif decision.action == "redact":
                logger.info(
                    "🔒 PRIVACY REDACT: Saving sanitized stub for [%s] (Reason: %s)",
                    ctx.app_name, decision.reason
                )
                now_iso = datetime.now(timezone.utc).isoformat()
                record = CaptureRecord(
                    timestamp=now_iso,
                    app_name=ctx.app_name,
                    window_title="[REDACTED]",
                    url=None,
                    ocr_text="[REDACTED BY PRIVACY GATEKEEPER]",
                    screenshot_path=None,
                    phash=hash_str,
                    width=img.width,
                    height=img.height,
                    is_redacted=1,
                    metadata={"reason": decision.reason, "rule": decision.matched_rule},
                )
                record_id = self.storage.save_capture(record)
                record.id = record_id
                return record

        # 5. Extract OCR text
        ocr_start = time.perf_counter()
        ocr_text = self.ocr_engine.extract_text(img)
        ocr_duration_ms = (time.perf_counter() - ocr_start) * 1000

        # 6. Save compressed screenshot to disk
        now = datetime.now(timezone.utc)
        ts_slug = now.strftime("%Y%m%d_%H%M%S_%f")[:19]
        fmt_ext = "jpg" if self.config.capture.image_format.lower() in ("jpg", "jpeg") else "webp"
        filename = f"{ts_slug}_{hash_str[:8]}.{fmt_ext}"
        screenshot_file = self.screenshots_dir / filename
        saved_path = self.capturer.save_image(img, screenshot_file)

        # 7. Persist to SQLite & FTS5
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
            is_redacted=0,
            metadata={
                "change_distance": distance,
                "ocr_duration_ms": round(ocr_duration_ms, 2),
                "process_id": ctx.process_id,
            },
        )
        record_id = self.storage.save_capture(record)
        record.id = record_id

        logger.info(
            "📸 CAPTURE #%d: App='%s' | Title='%.40s...' | URL=%s | OCR=%d chars (%.1fms)",
            record_id,
            ctx.app_name,
            ctx.window_title,
            ctx.url or "None",
            len(ocr_text),
            ocr_duration_ms,
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
