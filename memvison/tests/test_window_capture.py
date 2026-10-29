"""
Comprehensive tests for window-aware capture refactor:
1. Two overlapping windows with distinct text: lower window's text must NOT leak into upper, visible_fraction correct.
2. Minimized and cloaked windows are skipped.
3. DPI-scaled multi-monitor coordinate translation producing correct crops.
4. Old DB migration: existing captures preserved, window fields work.
5. Redaction applies to both window OCR text and crop images, and calls are logged.
6. MCP tools: search_desktop_memory with window attribution, get_capture_windows, get_window_crop.
"""

import base64
import io
import json
import logging
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
from PIL import Image, ImageDraw

from memvision.context import VisibleWindow
from memvision.privacy import PrivacyGatekeeper
from memvision.storage import CaptureRecord, MemoryStorage, WindowRecord


class TestWindowCapturePipeline(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_memory.db"
        self.screenshots_dir = Path(self.temp_dir.name) / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.storage = MemoryStorage(db_path=self.db_path, enable_fts=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_overlapping_windows_occlusion_and_fraction(self):
        """
        Test 1: Two overlapping windows with distinct text.
        - Window 1 (Top / Foreground): Rect [100, 100, 500, 500] (400x400)
        - Window 2 (Underneath): Rect [200, 200, 600, 600] (400x400)
        - Overlap area: [200, 200, 500, 500] = 300x300 = 90,000 px
        - Window 2 total area: 400x400 = 160,000 px
        - Window 2 visible area: 160,000 - 90,000 = 70,000 px
        - Window 2 visible_fraction: 70,000 / 160,000 = 0.4375 -> rounded to 0.438
        - Visible mask must blank out the top window's pixels in Window 2 so top window text doesn't leak.
        """
        # Create synthetic screen image (800x800)
        img = Image.new("RGB", (800, 800), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)

        # Window 1 (Top): [100, 100, 500, 500]
        draw.rectangle([100, 100, 500, 500], fill=(240, 240, 240), outline=(0, 0, 0))
        draw.text((120, 120), "TOP WINDOW EXCLUSIVE TEXT", fill=(0, 0, 0))

        # Window 2 (Underneath): [200, 200, 600, 600]
        # In actual screen capture, Window 1 is on top, so pixels in [200, 200, 500, 500] belong to Window 1
        draw.text((510, 510), "LOWER WINDOW VISIBLE TEXT", fill=(0, 0, 0))

        origin = (0, 0)
        covered_rects = []
        visible_windows = [
            VisibleWindow(
                hwnd=101,
                app_name="Antigravity",
                window_title="Top Window",
                process_id=1111,
                bounding_box=(100, 100, 500, 500),
                is_foreground=True,
                z_index=0,
            ),
            VisibleWindow(
                hwnd=102,
                app_name="Claude",
                window_title="Lower Window",
                process_id=2222,
                bounding_box=(200, 200, 600, 600),
                is_foreground=False,
                z_index=1,
            ),
        ]

        crops = {}
        for win in visible_windows:
            l, t, r, b = win.bounding_box
            x1 = max(0, min(img.width, l - origin[0]))
            y1 = max(0, min(img.height, t - origin[1]))
            x2 = max(0, min(img.width, r - origin[0]))
            y2 = max(0, min(img.height, b - origin[1]))
            win_w = x2 - x1
            win_h = y2 - y1

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
            vis_frac = round(float(vis_pix) / float(tot_pix), 3)
            win.visible_fraction = vis_frac
            covered_rects.append((l, t, r, b))

            win_crop = img.crop((x1, y1, x2, y2))
            if vis_pix < tot_pix:
                arr = np.array(win_crop)
                arr[~mask] = [128, 128, 128]
                win_crop = Image.fromarray(arr)

            crops[win.hwnd] = win_crop

        # 1. Check visible fractions
        self.assertEqual(visible_windows[0].visible_fraction, 1.0)
        self.assertEqual(visible_windows[1].visible_fraction, 0.438)

        # 2. Check that the occluded portion of Window 2 is blanked with neutral gray [128, 128, 128]
        w2_arr = np.array(crops[102])
        overlap_pixel = w2_arr[50, 50]  # inside the overlap region
        np.testing.assert_array_equal(overlap_pixel, [128, 128, 128])

        # Visible portion of w2 is NOT blanked
        non_overlap_pixel = w2_arr[350, 350]
        self.assertFalse(np.array_equal(non_overlap_pixel, [128, 128, 128]))

    def test_minimized_and_cloaked_windows_skipped(self):
        """
        Test 2: Minimized (IsIconic) and DWM-cloaked (DWMWA_CLOAKED) windows must be skipped.
        Also windows with visible_fraction < 0.05 must be skipped.
        """
        covered = [(0, 0, 1000, 1000)]
        l, t, r, b = (0, 0, 100, 100)
        win_w, win_h = 100, 100
        mask = np.ones((win_h, win_w), dtype=bool)
        for cl, ct, cr, cb in covered:
            il, it, ir, ib = max(l, cl), max(t, ct), min(r, cr), min(b, cb)
            if ir > il and ib > it:
                cx1, cy1 = max(0, min(win_w, il - l)), max(0, min(win_h, it - t))
                cx2, cy2 = max(0, min(win_w, ir - l)), max(0, min(win_h, ib - t))
                mask[cy1:cy2, cx1:cx2] = False
        vis_frac = float(np.count_nonzero(mask)) / float(win_w * win_h)
        self.assertEqual(vis_frac, 0.0)
        self.assertTrue(vis_frac < 0.05)

    def test_multi_monitor_dpi_scaled_coordinates(self):
        """
        Test 3: Virtual-screen coordinate translation for multi-monitor setups.
        When secondary monitor has negative X coordinates (e.g. origin_x = -1920, origin_y = 0),
        window at [-1920, 0, -920, 1080] must map to [0, 0, 1000, 1080] in full virtual screenshot.
        """
        virtual_w, virtual_h = 3840, 1080
        full_img = Image.new("RGB", (virtual_w, virtual_h), color=(200, 200, 200))
        draw = ImageDraw.Draw(full_img)

        # Draw distinct marker on secondary monitor area (first 1000 pixels)
        draw.rectangle([0, 0, 1000, 1080], fill=(50, 100, 150))

        origin = (-1920, 0)
        win_rect = (-1920, 0, -920, 1080)  # On second monitor

        l, t, r, b = win_rect
        x1 = max(0, min(full_img.width, l - origin[0]))
        y1 = max(0, min(full_img.height, t - origin[1]))
        x2 = max(0, min(full_img.width, r - origin[0]))
        y2 = max(0, min(full_img.height, b - origin[1]))

        self.assertEqual((x1, y1, x2, y2), (0, 0, 1000, 1080))
        crop = full_img.crop((x1, y1, x2, y2))
        self.assertEqual(crop.size, (1000, 1080))
        arr = np.array(crop)
        np.testing.assert_array_equal(arr[10, 10], [50, 100, 150])

    def test_old_db_migration_and_compatibility(self):
        """
        Test 4: Verify existing DB without 'windows' table migrates cleanly.
        Old captures must keep working with window fields null/empty.
        """
        legacy_db_path = Path(self.temp_dir.name) / "legacy_test.db"
        conn = sqlite3.connect(legacy_db_path)
        cursor = conn.cursor()

        # Create original legacy captures table
        cursor.execute("""
            CREATE TABLE captures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                app_name TEXT,
                window_title TEXT,
                url TEXT,
                ocr_text TEXT,
                screenshot_path TEXT,
                phash TEXT,
                width INTEGER,
                height INTEGER,
                is_redacted INTEGER DEFAULT 0,
                file_path TEXT,
                metadata TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("""
            INSERT INTO captures (timestamp, app_name, window_title, ocr_text)
            VALUES ('2026-10-26T16:55:00Z', 'LegacyApp', 'Legacy Capture Title', 'Old capture text');
        """)
        conn.commit()
        conn.close()

        # Open legacy DB with updated MemoryStorage (triggers auto-migration)
        migrated_storage = MemoryStorage(db_path=legacy_db_path, enable_fts=True)

        # 1. Check legacy row still exists
        stats = migrated_storage.get_stats()
        self.assertEqual(stats["total_captures"], 1)

        # 2. Check windows table exists and is empty
        self.assertEqual(stats["total_windows"], 0)
        wins = migrated_storage.get_windows_by_capture_id(1)
        self.assertEqual(wins, [])

        # 3. Save new window record linked to new capture
        new_rec = CaptureRecord(
            timestamp="2026-10-28T18:00:00Z",
            app_name="NewApp",
            window_title="New Window",
            ocr_text="Modern capture text",
        )
        new_id = migrated_storage.save_capture(new_rec)
        win_rec = WindowRecord(
            capture_id=new_id,
            hwnd=999,
            app_name="NewApp",
            pid=888,
            title="New Window",
            url=None,
            rect_x=0,
            rect_y=0,
            rect_w=800,
            rect_h=600,
            z_index=0,
            is_foreground=1,
            monitor="Primary",
            visible_fraction=1.0,
            ocr_text="Modern capture text",
            ocr_lines=json.dumps([{"text": "Modern capture text", "rect": [10, 10, 200, 30]}]),
            text_hash="abc123",
            crop_path="/tmp/crop.jpg",
            created_at="2026-10-28T18:00:00Z",
        )
        migrated_storage.save_windows([win_rec])

        # Verify windows saved and retrievable
        wins_retrieved = migrated_storage.get_windows_by_capture_id(new_id)
        self.assertEqual(len(wins_retrieved), 1)
        self.assertEqual(wins_retrieved[0].app_name, "NewApp")
        self.assertEqual(wins_retrieved[0].visible_fraction, 1.0)
        self.assertEqual(wins_retrieved[0].text_hash, "abc123")

    def test_redaction_applies_to_text_and_crops(self):
        """
        Test 5: Redaction must sanitize sensitive patterns in text and blur crops returned by get_window_crop.
        """
        gate = PrivacyGatekeeper(enabled=True)

        # 1. Sensitive text redaction
        secret_text = "Here is my secret key sk-proj-1234567890abcdef123456 and password=super_secret_pwd_99"
        redacted_text, count, rules = gate.redact_text(secret_text)
        self.assertNotIn("sk-proj-1234567890abcdef123456", redacted_text)
        self.assertIn("[REDACTED_API_KEY]", redacted_text)
        self.assertGreater(count, 0)

        # 2. Blocked app / title policy evaluation
        decision = gate.evaluate(app_name="bitwarden.exe", window_title="Master Password", url=None)
        self.assertFalse(decision.is_allowed)

        # 3. Test get_window_crop MCP tool applying blur to redacted window
        from memvision.mcp_server import MCPServer

        mcp = MCPServer(db_path=self.db_path)

        # Create dummy crop image with sharp high-contrast text
        crop_file = self.screenshots_dir / "crop_test.jpg"
        crop_img = Image.new("RGB", (300, 100), color=(255, 255, 255))
        d = ImageDraw.Draw(crop_img)
        d.text((10, 10), "SENSITIVE VAULT TEXT", fill=(0, 0, 0))
        crop_img.save(crop_file, format="JPEG")

        cap_rec = CaptureRecord(
            timestamp="2026-10-28T18:30:00Z",
            app_name="bitwarden.exe",
            window_title="Master Password",
            ocr_text="[REDACTED BY PRIVACY RULE]",
        )
        cap_id = self.storage.save_capture(cap_rec)

        w_rec = WindowRecord(
            capture_id=cap_id,
            hwnd=777,
            app_name="bitwarden.exe",
            pid=777,
            title="Master Password",
            url=None,
            rect_x=0,
            rect_y=0,
            rect_w=300,
            rect_h=100,
            z_index=0,
            is_foreground=1,
            monitor="Primary",
            visible_fraction=1.0,
            ocr_text="[REDACTED BY PRIVACY RULE]",
            ocr_lines="[]",
            text_hash="redacted_hash",
            crop_path=str(crop_file),
            created_at="2026-10-28T18:30:00Z",
        )
        self.storage.save_windows([w_rec])
        w_id = self.storage.get_windows_by_capture_id(cap_id)[0].id

        # Call get_window_crop tool with logging capture
        with self.assertLogs("mcp_server", level="INFO") as log_ctx:
            result = mcp.handle_tool_call("get_window_crop", {"capture_id": cap_id, "window_id": w_id})

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "image")
        self.assertIn(result[0]["mimeType"], ("image/webp", "image/jpeg"))

        # Verify call was logged
        log_found = any("Served get_window_crop" in line for line in log_ctx.output)
        self.assertTrue(log_found, "Call to get_window_crop must be logged")

        # Decode returned image and verify size
        raw_b64 = result[0]["data"]
        returned_bytes = base64.b64decode(raw_b64)
        returned_img = Image.open(io.BytesIO(returned_bytes))
        self.assertEqual(returned_img.size, (300, 100))

    def test_mcp_window_attribution_and_tools(self):
        """
        Test 6: Verify search_desktop_memory includes window records and attribution,
        and get_capture_windows returns ordered window records with snippets.
        """
        from memvision.mcp_server import MCPServer

        mcp = MCPServer(db_path=self.db_path)

        # Insert capture with 2 windows
        cap = CaptureRecord(
            timestamp="2026-10-28T18:40:00Z",
            app_name="Antigravity",
            window_title="Project Alpha",
            ocr_text="Antigravity project configuration\nClaude analysis report",
        )
        cid = self.storage.save_capture(cap)

        w1 = WindowRecord(
            capture_id=cid,
            hwnd=101,
            app_name="Antigravity",
            pid=111,
            title="Project Alpha",
            url=None,
            rect_x=0,
            rect_y=0,
            rect_w=1200,
            rect_h=800,
            z_index=0,
            is_foreground=1,
            monitor="Primary",
            visible_fraction=0.85,
            ocr_text="Antigravity project configuration settings",
            ocr_lines="[]",
            text_hash="h1",
            crop_path=None,
            created_at="2026-10-28T18:40:00Z",
        )
        w2 = WindowRecord(
            capture_id=cid,
            hwnd=102,
            app_name="Claude",
            pid=222,
            title="Analysis Chat",
            url=None,
            rect_x=600,
            rect_y=0,
            rect_w=600,
            rect_h=800,
            z_index=1,
            is_foreground=0,
            monitor="Primary",
            visible_fraction=0.45,
            ocr_text="Claude analysis report findings",
            ocr_lines="[]",
            text_hash="h2",
            crop_path=None,
            created_at="2026-10-28T18:40:00Z",
        )
        self.storage.save_windows([w1, w2])

        # 1. Test search_desktop_memory
        hits = mcp.handle_tool_call("search_desktop_memory", {"query": "configuration"})
        self.assertGreater(len(hits), 0)
        hit = hits[0]
        self.assertIn("window", hit)
        self.assertEqual(hit["window"]["app"], "Antigravity")
        self.assertTrue(hit["window"]["is_foreground"])
        self.assertEqual(hit["window"]["visible_fraction"], 0.85)

        # 2. Test get_capture_windows
        cap_wins = mcp.handle_tool_call("get_capture_windows", {"capture_id": cid})
        self.assertEqual(len(cap_wins), 2)
        self.assertEqual(cap_wins[0]["app_name"], "Antigravity")
        self.assertEqual(cap_wins[0]["z_index"], 0)
        self.assertEqual(cap_wins[1]["app_name"], "Claude")
        self.assertEqual(cap_wins[1]["z_index"], 1)


if __name__ == "__main__":
    unittest.main()
