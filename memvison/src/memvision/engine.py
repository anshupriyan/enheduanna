"""
Continuous Capture & Store Engine for mem-vision-mcp.
Orchestrates screen sampling, change detection, context extraction, privacy filtering, OCR, and storage.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
import numpy as np
from PIL import Image, ImageFilter

from memvision.capture import ScreenCapturer
from memvision.change_detector import ChangeDetector
from memvision.config import AppConfig
from memvision.context import ContextExtractor, WindowContext, VisibleWindow
from memvision.ocr import LocalOCREngine
from memvision.privacy import PrivacyGatekeeper
from memvision.storage import CaptureRecord, MemoryStorage, WindowRecord

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
        self.crops_dir = self.screenshots_dir.parent / "crops"
        self.crops_dir.mkdir(parents=True, exist_ok=True)
        self._window_text_hashes: dict[Any, str] = {}

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

    def _prune_crops(self, max_size_mb: int = 500, max_age_days: int = 7) -> int:
        """Prunes oldest crops if total directory size exceeds max_size_mb or age exceeds max_age_days."""
        if not self.crops_dir.exists():
            return 0
        try:
            now = time.time()
            max_age_sec = max_age_days * 86400
            files = list(self.crops_dir.glob("*.jpg"))
            total_bytes = sum(f.stat().st_size for f in files)
            pruned = 0
            if total_bytes > max_size_mb * 1024 * 1024 or any(now - f.stat().st_mtime > max_age_sec for f in files):
                files.sort(key=lambda f: f.stat().st_mtime)
                for f in files:
                    age = now - f.stat().st_mtime
                    if age > max_age_sec or total_bytes > max_size_mb * 1024 * 1024:
                        sz = f.stat().st_size
                        f.unlink(missing_ok=True)
                        total_bytes -= sz
                        pruned += 1
            return pruned
        except Exception as e:
            logger.debug("Crop pruning error: %s", e)
            return 0

    def capture_once(self, force: bool = False) -> Optional[CaptureRecord]:
        """
        Executes a single window-aware capture tick.
        Enumerates visible windows in Z-order, computes occlusion masks,
        OCRs each window in native resolution with covered pixels blanked out,
        deduplicates text and window crops, and stores window records.
        """
        # 1. Grab screen in 100% full native resolution in memory
        try:
            img = self.capturer.capture()
        except Exception as e:
            logger.error("Screen capture failed: %s", e)
            return None

        origin = getattr(self.capturer, "last_capture_origin", (0, 0))

        # 2. Extract active foreground window and visible top-level windows in Z-order
        ctx: WindowContext = self.context_extractor.get_active_context()
        visible_windows: list[VisibleWindow] = self.context_extractor.get_visible_windows()

        # 2.1 Detect visible windows violating privacy rules
        blocked_windows = self.privacy_gate.filter_blocked_windows(visible_windows)
        active_decision = self.privacy_gate.evaluate(
            app_name=ctx.app_name,
            window_title=ctx.window_title,
            url=ctx.url,
        )
        masked_names: list[str] = []

        if not active_decision.is_allowed:
            img_area = max(1, img.width * img.height)
            win_ratio = 1.0
            if ctx.bounding_box:
                l, t, r, b = ctx.bounding_box
                win_area = max(0, r - l) * max(0, b - t)
                win_ratio = min(1.0, win_area / img_area)

            allowed_windows = [
                w for w in visible_windows
                if self.privacy_gate.evaluate(w.app_name, w.window_title).is_allowed
            ]

            if win_ratio >= 0.85 or not allowed_windows:
                if active_decision.action == "drop":
                    logger.info(
                        "🔒 PRIVACY DROP: Ignored capture for [%s] (Rule: %s, Reason: %s)",
                        ctx.app_name, active_decision.matched_rule, active_decision.reason
                    )
                    return None
                elif active_decision.action == "redact":
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

        if blocked_windows:
            img, masked_count = self.capturer.redact_blocked_windows(img, blocked_windows, stamp_badge=False)
            masked_names = [getattr(w, "app_name", "Unknown") for w, _ in blocked_windows]

        # 3. Check for visual change across screen
        has_changed, distance, hash_str = self.change_detector.evaluate_change(img)
        if not has_changed and not force:
            logger.debug(
                "Tick: No visual change detected (dist=%d <= thresh=%d)",
                distance, self.config.capture.hash_threshold
            )
            return None

        now = datetime.now(timezone.utc)
        now_epoch = time.time()
        ts_slug = now.strftime("%Y%m%d_%H%M%S_%f")[:19]

        # 4. Occlusion Tracking & Visibility Masking
        covered_rects: list[tuple[int, int, int, int]] = []
        processed_windows: list[dict] = []

        for win in visible_windows:
            l, t, r, b = win.bounding_box
            x1 = max(0, min(img.width, l - origin[0]))
            y1 = max(0, min(img.height, t - origin[1]))
            x2 = max(0, min(img.width, r - origin[0]))
            y2 = max(0, min(img.height, b - origin[1]))
            win_w = x2 - x1
            win_h = y2 - y1
            if win_w < 10 or win_h < 10:
                continue

            # Occlusion mask: True = visible, False = occluded by higher-Z windows
            mask = np.ones((win_h, win_w), dtype=bool)
            for cl, ct, cr, cb in covered_rects:
                il = max(l, cl)
                it = max(t, ct)
                ir = min(r, cr)
                ib = min(b, cb)
                if ir > il and ib > it:
                    cx1 = max(0, min(win_w, il - l))
                    cy1 = max(0, min(win_h, it - t))
                    cx2 = max(0, min(win_w, ir - l))
                    cy2 = max(0, min(win_h, ib - t))
                    mask[cy1:cy2, cx1:cx2] = False

            vis_pix = int(np.count_nonzero(mask))
            tot_pix = win_w * win_h
            vis_frac = round(float(vis_pix) / float(tot_pix), 3) if tot_pix > 0 else 0.0

            # Requirement 2: Skip windows with visible_fraction < 0.05
            if vis_frac < 0.05:
                continue

            covered_rects.append((l, t, r, b))
            win.visible_fraction = vis_frac

            # Requirement 3 & 4: Crop from native-resolution frame in memory
            win_crop = img.crop((x1, y1, x2, y2))
            if vis_pix < tot_pix:
                # Blank out occluded pixels with neutral gray so text underneath doesn't leak
                arr = np.array(win_crop)
                arr[~mask] = [128, 128, 128]
                win_crop = Image.fromarray(arr)

            # Crop tightly to visible unoccluded bounding box for OCR
            y_indices, x_indices = np.where(mask)
            if len(x_indices) > 0 and len(y_indices) > 0:
                min_vx, max_vx = int(np.min(x_indices)), int(np.max(x_indices)) + 1
                min_vy, max_vy = int(np.min(y_indices)), int(np.max(y_indices)) + 1
                ocr_crop = win_crop.crop((min_vx, min_vy, max_vx, max_vy))
                offset_x = min_vx
                offset_y = min_vy
            else:
                ocr_crop = win_crop
                offset_x = 0
                offset_y = 0

            processed_windows.append({
                "window": win,
                "crop": win_crop,
                "ocr_crop": ocr_crop,
                "offset": (offset_x, offset_y),
                "rect": (l, t, r, b),
            })

        # 5. Per-Window OCR, Privacy Gating & Deduplication
        saved_window_records: list[WindowRecord] = []
        aggregate_ocr_sections: list[str] = []
        total_redactions = 0
        all_matched_rules: list[str] = []
        ocr_start = time.perf_counter()

        for item in processed_windows:
            w: VisibleWindow = item["window"]
            ocr_crop: Image.Image = item["ocr_crop"]
            ox, oy = item["offset"]

            # Privacy rule evaluation per window
            decision = self.privacy_gate.evaluate(app_name=w.app_name, window_title=w.window_title, url=w.url)
            if decision.action == "drop":
                continue

            if decision.action == "redact":
                sanitized_text = "[REDACTED BY PRIVACY RULE]"
                lines_json = None
                # Apply redaction blur to crop
                item["crop"] = item["crop"].filter(ImageFilter.GaussianBlur(radius=20))
                total_redactions += 1
                all_matched_rules.append(decision.matched_rule or "privacy_redact")
            else:
                raw_text, raw_lines = self.ocr_engine.extract_text_and_lines(ocr_crop)
                for line in raw_lines:
                    line["rect"][0] += ox
                    line["rect"][1] += oy
                    for word in line.get("words", []):
                        word["rect"][0] += ox
                        word["rect"][1] += oy

                sanitized_text, r_cnt, r_rules = self.privacy_gate.redact_text(raw_text)
                total_redactions += r_cnt
                all_matched_rules.extend(r_rules)
                for line in raw_lines:
                    line["text"], _, _ = self.privacy_gate.redact_text(line["text"])
                lines_json = json.dumps(raw_lines)

            # Dedupe: hash each window's OCR text
            text_hash = hashlib.sha256(sanitized_text.encode("utf-8")).hexdigest()[:16]
            prev_hash = self._window_text_hashes.get(w.hwnd) or self._window_text_hashes.get((w.app_name, w.window_title))
            text_changed = (prev_hash != text_hash)
            self._window_text_hashes[w.hwnd] = text_hash
            self._window_text_hashes[(w.app_name, w.window_title)] = text_hash

            # Save native-resolution JPEG crop (q70, max 1600px wide) only when window text changes or becomes foreground
            crop_path = None
            if w.is_foreground or text_changed or force:
                crop_to_save = item["crop"]
                if crop_to_save.width > 1600:
                    ratio = 1600.0 / crop_to_save.width
                    new_h = max(1, int(crop_to_save.height * ratio))
                    crop_to_save = crop_to_save.resize((1600, new_h), Image.Resampling.LANCZOS)
                app_slug = "".join(c for c in w.app_name.lower() if c.isalnum() or c in "_-")[:12]
                crop_filename = f"{ts_slug}_z{w.z_index}_{app_slug}_{text_hash[:6]}.jpg"
                crop_file = self.crops_dir / crop_filename
                try:
                    crop_to_save.save(crop_file, format="JPEG", quality=70, optimize=True)
                    crop_path = str(crop_file)
                except Exception as e:
                    logger.debug("Failed to save window crop %s: %s", crop_file, e)

            l, t, r, b = item["rect"]
            w_rec = WindowRecord(
                capture_id=0,
                hwnd=w.hwnd,
                app_name=w.app_name,
                pid=w.process_id,
                title=w.window_title,
                url=w.url,
                rect_x=l,
                rect_y=t,
                rect_w=r - l,
                rect_h=b - t,
                z_index=w.z_index,
                is_foreground=1 if w.is_foreground else 0,
                monitor=w.monitor,
                visible_fraction=w.visible_fraction,
                ocr_text=sanitized_text,
                ocr_lines=lines_json,
                text_hash=text_hash,
                crop_path=crop_path,
                created_at=now.isoformat(),
            )
            saved_window_records.append(w_rec)

            if sanitized_text.strip():
                fg_tag = "foreground" if w.is_foreground else "background"
                pct = int(w.visible_fraction * 100)
                aggregate_ocr_sections.append(
                    f"[{w.app_name} | {w.window_title} ({fg_tag}, {pct}% visible)]\n{sanitized_text}"
                )

        ocr_duration_ms = (time.perf_counter() - ocr_start) * 1000

        # Fallback if no window records were created (headless or system desktop)
        if not saved_window_records:
            raw_text = self.ocr_engine.extract_text(img)
            sanitized_text, r_cnt, _ = self.privacy_gate.redact_text(raw_text)
            total_redactions += r_cnt
            aggregated_ocr = sanitized_text
        else:
            aggregated_ocr = "\n\n".join(aggregate_ocr_sections)

        # 6. Sanitize title and URL
        sanitized_title, title_redact_count, title_matched_rules = self.privacy_gate.redact_text(ctx.window_title)
        sanitized_url, url_redact_count, url_matched_rules = (
            self.privacy_gate.redact_url(ctx.url) if ctx.url else (None, 0, [])
        )
        total_redactions += title_redact_count + url_redact_count
        all_matched_rules.extend(title_matched_rules + url_matched_rules)
        all_matched_rules = list(set(all_matched_rules))

        # 7. Text stability evaluation for video suppression
        is_same_window = (
            self._last_saved_record is not None
            and (self._last_saved_record.app_name or "").lower() == (ctx.app_name or "").lower()
            and self._last_saved_record.window_title == sanitized_title
        )

        if is_same_window and not force and self.config.capture.video_suppression_enabled:
            prev_ocr = self._last_saved_record.ocr_text or ""
            is_video_static, is_draft_expansion, char_sim, containment = self._evaluate_text_stability(
                prev_text=prev_ocr,
                curr_text=aggregated_ocr,
            )
            if is_video_static:
                logger.debug(
                    "🎬 VIDEO SUPPRESSION: Skipped capture for [%s] '%.40s' (OCR text identical/stable, sim=%.2f)",
                    ctx.app_name, sanitized_title, char_sim
                )
                return None

        # 8. Save preview image downscaled for storage
        ts_slug = now.strftime("%Y%m%d_%H%M%S_%f")[:19]
        fmt_ext = "jpg" if self.config.capture.image_format.lower() in ("jpg", "jpeg") else "webp"
        filename = f"{ts_slug}_{hash_str[:8]}.{fmt_ext}"
        screenshot_file = self.screenshots_dir / filename

        preview_img = img
        if blocked_windows:
            preview_img = img.copy()
            self.capturer.redact_blocked_windows(preview_img, blocked_windows, stamp_badge=True)

        saved_path, thumb_w, thumb_h = self.capturer.save_image(preview_img, screenshot_file, downscale_for_storage=True)

        is_redacted_flag = 1 if (total_redactions > 0 or bool(blocked_windows)) else 0

        # 9. Persist CaptureRecord and WindowRecords
        record = CaptureRecord(
            timestamp=now.isoformat(),
            app_name=ctx.app_name,
            window_title=sanitized_title,
            url=sanitized_url,
            ocr_text=aggregated_ocr,
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
                "virtual_origin": list(origin),
                "window_count": len(saved_window_records),
                "windows": [
                    {
                        "app": w.app_name,
                        "title": w.title,
                        "is_foreground": bool(w.is_foreground),
                        "visible_fraction": w.visible_fraction,
                        "has_crop": bool(w.crop_path),
                    }
                    for w in saved_window_records
                ],
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

        # Save linked windows
        for w_rec in saved_window_records:
            w_rec.capture_id = record_id
        self.storage.save_windows(saved_window_records)

        # Prune old crops to enforce storage limit
        self._prune_crops()

        logger.info(
            "📸 CAPTURE #%d: Windows=%d | Fore='%s' (%.30s) | OCR=%d chars (%.1fms)",
            record_id,
            len(saved_window_records),
            ctx.app_name,
            sanitized_title,
            len(aggregated_ocr),
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
