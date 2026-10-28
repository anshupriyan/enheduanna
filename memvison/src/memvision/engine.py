"""
Continuous Capture & Store Engine for mem-vision-mcp.
Orchestrates screen sampling, change detection, context extraction, privacy filtering, OCR, and storage.
"""

from __future__ import annotations

import difflib
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
        self._last_saved_record: Optional[CaptureRecord] = None
        self._last_saved_time: float = 0.0

    def register_step_callback(self, cb: Callable[[CaptureRecord], None]) -> None:
        """Register a callback invoked whenever a capture is committed."""
        self._step_callbacks.append(cb)

    def _evaluate_text_stability(
        self,
        prev_text: str,
        curr_text: str,
    ) -> tuple[bool, bool, float, float]:
        """
        Evaluates whether current text represents:
        1. is_video_static: Moving pixels with essentially identical text (e.g. video playback / stream / animation).
        2. is_draft_expansion: Incremental typing expanding existing text (e.g. typing a 2nd paragraph in a document).

        Returns:
            (is_video_static, is_draft_expansion, char_similarity, containment_ratio)
        """
        p_clean = " ".join(prev_text.split()).strip().lower()
        c_clean = " ".join(curr_text.split()).strip().lower()

        # Both empty (e.g. fullscreen video player where controls auto-hide)
        if not p_clean and not c_clean:
            return True, False, 1.0, 1.0

        # One empty and other has content -> genuine content appearance/disappearance
        if not p_clean or not c_clean:
            return False, False, 0.0, 0.0

        # Fast character similarity using SequenceMatcher.quick_ratio
        char_sim = difflib.SequenceMatcher(None, p_clean, c_clean).quick_ratio()

        # Word sets for containment
        p_words = set(p_clean.split())
        c_words = set(c_clean.split())
        intersection = len(p_words & c_words)
        containment = intersection / max(1, len(p_words))

        # 1. Video / Animation check: Text is nearly identical
        threshold = self.config.capture.text_stability_threshold
        is_video_static = char_sim >= threshold or (containment >= 0.95 and abs(len(c_clean) - len(p_clean)) < 20)

        # 2. Incremental Draft check: Text grew longer, and previous words are largely preserved
        is_draft_expansion = (
            not is_video_static
            and len(c_clean) > len(p_clean)
            and containment >= 0.85
        )

        return is_video_static, is_draft_expansion, char_sim, containment

    def capture_once(self, force: bool = False) -> Optional[CaptureRecord]:
        """
        Executes a single capture tick.
        Useful for on-demand captures, unit testing, and CLI dry-runs.
        Implements Approach 1: Spatial Window Masking ("The Blackout Curtain"),
        Video/Animation Suppression, and Incremental Draft Collapsing.
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

        # 7.1 Text-Level & URL Privacy Gating (Redact API keys, tokens, OAuth state, doc hashes)
        sanitized_ocr, ocr_redact_count, ocr_matched_rules = self.privacy_gate.redact_text(ocr_text)
        sanitized_title, title_redact_count, title_matched_rules = self.privacy_gate.redact_text(ctx.window_title)
        sanitized_url, url_redact_count, url_matched_rules = (
            self.privacy_gate.redact_url(ctx.url) if ctx.url else (None, 0, [])
        )

        total_redactions = ocr_redact_count + title_redact_count + url_redact_count
        all_matched_rules = list(set(ocr_matched_rules + title_matched_rules + url_matched_rules))

        if total_redactions > 0:
            logger.info(
                "🔒 CONTENT REDACTION: Redacted %d sensitive token(s) [%s] from capture of '%s'.",
                total_redactions,
                ", ".join(all_matched_rules),
                ctx.app_name,
            )

        # 7.2 Text & Title Stability Gating (Video Suppression & Draft Collapsing)
        now_epoch = time.time()
        is_same_window = (
            self._last_saved_record is not None
            and (self._last_saved_record.app_name or "").lower() == (ctx.app_name or "").lower()
            and self._last_saved_record.window_title == sanitized_title
        )

        now = datetime.now(timezone.utc)
        is_redacted_flag = 1 if (total_redactions > 0 or bool(blocked_windows)) else 0

        if is_same_window and not force:
            prev_ocr = self._last_saved_record.ocr_text or ""
            is_video_static, is_draft_expansion, char_sim, containment = self._evaluate_text_stability(
                prev_text=prev_ocr,
                curr_text=sanitized_ocr,
            )

            # Case A: Video / Animation Suppression
            # The pixels changed (dHash triggered), but the text on screen is unchanged!
            if self.config.capture.video_suppression_enabled and is_video_static:
                logger.info(
                    "🎬 VIDEO SUPPRESSION: Skipped capture for [%s] '%.40s' (OCR text identical/stable, sim=%.2f)",
                    ctx.app_name,
                    sanitized_title,
                    char_sim,
                )
                return None

            # Case B: Incremental Document Drafting / Accumulation
            # The user typed more into the same document within the collapse window.
            # We supersede the previous capture so only the accumulated state is kept!
            time_since_last = now_epoch - self._last_saved_time
            if (
                self.config.capture.draft_collapse_enabled
                and is_draft_expansion
                and time_since_last <= self.config.capture.draft_collapse_window_sec
            ):
                # Save new screenshot with the accumulated text
                ts_slug = now.strftime("%Y%m%d_%H%M%S_%f")[:19]
                fmt_ext = "jpg" if self.config.capture.image_format.lower() in ("jpg", "jpeg") else "webp"
                filename = f"{ts_slug}_{hash_str[:8]}.{fmt_ext}"
                screenshot_file = self.screenshots_dir / filename

                preview_img = img
                if blocked_windows:
                    preview_img = img.copy()
                    self.capturer.redact_blocked_windows(preview_img, blocked_windows, stamp_badge=True)

                saved_path, thumb_w, thumb_h = self.capturer.save_image(preview_img, screenshot_file, downscale_for_storage=True)

                # Delete obsolete partial draft screenshot
                old_screenshot = self._last_saved_record.screenshot_path
                if old_screenshot and old_screenshot != saved_path:
                    try:
                        Path(old_screenshot).unlink(missing_ok=True)
                    except Exception as e:
                        logger.debug("Could not remove superseded draft screenshot: %s", e)

                # Update the existing record in-place in SQLite and FTS5
                prev_id = self._last_saved_record.id
                draft_count = (self._last_saved_record.metadata or {}).get("draft_accumulations", 0) + 1

                self._last_saved_record.timestamp = now.isoformat()
                self._last_saved_record.url = sanitized_url
                self._last_saved_record.ocr_text = sanitized_ocr
                self._last_saved_record.file_path = ctx.file_path
                self._last_saved_record.screenshot_path = saved_path
                self._last_saved_record.phash = hash_str
                self._last_saved_record.width = img.width
                self._last_saved_record.height = img.height
                self._last_saved_record.is_redacted = is_redacted_flag
                if not self._last_saved_record.metadata:
                    self._last_saved_record.metadata = {}
                self._last_saved_record.metadata.update({
                    "draft_accumulations": draft_count,
                    "superseded_chars": len(prev_ocr),
                    "accumulated_chars": len(sanitized_ocr),
                    "ocr_duration_ms": round(ocr_duration_ms, 2),
                    "storage_dimensions": f"{thumb_w}x{thumb_h}",
                    "file_path": ctx.file_path,
                    "workspace_path": ctx.workspace_path,
                    "is_ide": ctx.is_ide,
                })

                self.storage.update_capture(prev_id, self._last_saved_record)
                self._last_saved_time = now_epoch

                logger.info(
                    "📝 DRAFT COLLAPSE #%d: Updated accumulated text (+%d chars) for [%s] '%.40s'",
                    prev_id,
                    len(sanitized_ocr) - len(prev_ocr),
                    ctx.app_name,
                    sanitized_title,
                )

                for cb in self._step_callbacks:
                    try:
                        cb(self._last_saved_record)
                    except Exception as e:
                        logger.error("Error in capture callback: %s", e)

                return self._last_saved_record

        # 8. Save preview image to disk (Standard New Capture)
        # If any windows were masked, stamp sleek privacy badge on the saved preview
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
            window_title=sanitized_title,
            url=sanitized_url,
            ocr_text=sanitized_ocr,
            screenshot_path=saved_path,
            phash=hash_str,
            width=img.width,
            height=img.height,
            is_redacted=is_redacted_flag,
            file_path=ctx.file_path,
            metadata={
                "change_distance": distance,
                "ocr_duration_ms": round(ocr_duration_ms, 2),
                "process_id": ctx.process_id,
                "native_dimensions": f"{img.width}x{img.height}",
                "storage_dimensions": f"{thumb_w}x{thumb_h}",
                "spatial_masked_windows": list(set(masked_names)),
                "is_spatially_masked": bool(blocked_windows),
                "content_redacted_count": total_redactions,
                "content_redacted_rules": all_matched_rules,
                "file_path": ctx.file_path,
                "workspace_path": ctx.workspace_path,
                "is_ide": ctx.is_ide,
            },
        )
        record_id = self.storage.save_capture(record)
        record.id = record_id
        self._last_saved_record = record
        self._last_saved_time = now_epoch

        redact_info = f" [REDACTED: {total_redactions} tokens]" if total_redactions > 0 else ""
        mask_info = f" [MASKED: {', '.join(set(masked_names))}]" if masked_names else ""
        file_info = f" | File='{Path(ctx.file_path).name}'" if ctx.file_path else ""
        logger.info(
            "📸 CAPTURE #%d: App='%s' | Title='%.40s...' | URL=%s%s | OCR=%d chars (%.1fms)%s%s",
            record_id,
            ctx.app_name,
            sanitized_title,
            sanitized_url or "None",
            file_info,
            len(sanitized_ocr),
            ocr_duration_ms,
            mask_info,
            redact_info,
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

        import threading
        if threading.current_thread() is threading.main_thread():
            try:
                signal.signal(signal.SIGINT, _sig_handler)
                signal.signal(signal.SIGTERM, _sig_handler)
            except Exception:
                pass

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
