"""
Unit tests for Spatial Window Masking (The "Blackout Curtain").
Tests multi-window split-screen privacy redaction, coordinate translation,
and spatial rescue logic.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock
from PIL import Image, ImageDraw

from memvision.capture import ScreenCapturer, redact_regions
from memvision.config import AppConfig
from memvision.context import VisibleWindow, WindowContext
from memvision.engine import CaptureEngine
from memvision.privacy import PrivacyGatekeeper
from memvision.storage import MemoryStorage


def test_redact_regions_solid_blackout():
    """Verify that redact_regions paints a solid opaque curtain over the target bounding box."""
    # Create 800x400 canvas
    img = Image.new("RGB", (800, 400), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Left half: Public code
    draw.text((50, 50), "def calculate_total():", fill=(0, 0, 0))
    # Right half: Sensitive Discord secret
    draw.text((450, 50), "SECRET_DISCORD_TOKEN_XYZ", fill=(255, 0, 0))

    # Apply blackout curtain over the right half: (400, 0, 800, 400)
    regions = [((400, 0, 800, 400), "discord.exe")]
    masked_img, count = redact_regions(img, regions, origin=(0, 0), fill_color=(16, 16, 20), stamp_badge=False)

    assert count == 1
    # Check pixels on the right half: must be pure blackout color (16, 16, 20)
    for x in (450, 500, 600, 750):
        for y in (20, 50, 100, 200, 350):
            pixel = masked_img.getpixel((x, y))
            assert pixel == (16, 16, 20), f"Pixel at ({x}, {y}) was {pixel}, expected (16, 16, 20)"

    # Check pixels on the left half: must remain untouched white (255, 255, 255)
    pixel_left = masked_img.getpixel((10, 10))
    assert pixel_left == (255, 255, 255)


def test_redact_regions_coordinate_offset():
    """Verify coordinate translation when virtual desktop has negative origin (multi-monitor)."""
    # 1000x500 canvas captured with origin (-1920, 0)
    img = Image.new("RGB", (1000, 500), color=(200, 200, 200))

    # Window in virtual desktop coords: left=-1500, top=100, right=-1000, bottom=400
    # Relative to origin (-1920, 0): x1 = -1500 - (-1920) = 420, y1 = 100, x2 = 920, y2 = 400
    regions = [((-1500, 100, -1000, 400), "keepass.exe")]
    masked_img, count = redact_regions(img, regions, origin=(-1920, 0), fill_color=(0, 0, 0), stamp_badge=False)

    assert count == 1
    # Inside the translated box: (450, 200) should be black
    assert masked_img.getpixel((450, 200)) == (0, 0, 0)
    # Outside the translated box: (100, 100) should be original gray
    assert masked_img.getpixel((100, 100)) == (200, 200, 200)


def test_privacy_filter_blocked_windows():
    """Verify that PrivacyGatekeeper filters out restricted visible windows correctly."""
    rules = {
        "mode": "blocklist",
        "action_on_block": "drop",
        "blocked_apps": ["discord.exe", "1password.exe"],
        "blocked_window_titles": ["*Incognito*"],
    }
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f:
        json.dump(rules, f)
        rule_path = f.name

    try:
        gate = PrivacyGatekeeper(rule_path, enabled=True)

        windows = [
            VisibleWindow(hwnd=1, process_id=101, app_name="code.exe", window_title="main.py", bounding_box=(0, 0, 800, 600)),
            VisibleWindow(hwnd=2, process_id=102, app_name="discord.exe", window_title="Discord", bounding_box=(800, 0, 1600, 600)),
            VisibleWindow(hwnd=3, process_id=103, app_name="chrome.exe", window_title="Google Search - Incognito", bounding_box=(0, 600, 800, 1200)),
            VisibleWindow(hwnd=4, process_id=104, app_name="WindowsTerminal.exe", window_title="PowerShell", bounding_box=(800, 600, 1600, 1200)),
        ]

        blocked = gate.filter_blocked_windows(windows)
        blocked_apps = [w.app_name for w, _ in blocked]

        assert "discord.exe" in blocked_apps
        assert "chrome.exe" in blocked_apps  # Matched by Incognito title
        assert "code.exe" not in blocked_apps
        assert "WindowsTerminal.exe" not in blocked_apps
        assert len(blocked) == 2
    finally:
        Path(rule_path).unlink(missing_ok=True)


def test_spatial_masking_during_capture_tick():
    """Verify that CaptureEngine masks background restricted windows while keeping active app."""
    rules = {
        "mode": "blocklist",
        "action_on_block": "drop",
        "blocked_apps": ["discord.exe"],
    }
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f_rules:
        json.dump(rules, f_rules)
        rule_path = f_rules.name

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        screenshots_dir = Path(tmpdir) / "screenshots"

        cfg = AppConfig()
        cfg.privacy.config_path = rule_path
        cfg.storage.database_path = str(db_path)
        cfg.storage.screenshots_dir = str(screenshots_dir)
        cfg.ocr.enabled = False  # Skip OCR for fast testing

        engine = CaptureEngine(config=cfg)

        # Mock capturer to return an 800x400 white canvas
        mock_img = Image.new("RGB", (800, 400), color=(255, 255, 255))
        engine.capturer.capture = MagicMock(return_value=mock_img)
        engine.capturer.last_capture_origin = (0, 0)

        # Active window is VS Code on the left half (0, 0, 400, 400)
        engine.context_extractor.get_active_context = MagicMock(
            return_value=WindowContext(
                hwnd=10, process_id=1001, app_name="code.exe", window_title="main.py", bounding_box=(0, 0, 400, 400)
            )
        )

        # Visible windows: VS Code on left, Discord on right (400, 0, 800, 400)
        engine.context_extractor.get_visible_windows = MagicMock(
            return_value=[
                VisibleWindow(hwnd=10, process_id=1001, app_name="code.exe", window_title="main.py", bounding_box=(0, 0, 400, 400)),
                VisibleWindow(hwnd=20, process_id=2002, app_name="discord.exe", window_title="Discord", bounding_box=(400, 0, 800, 400)),
            ]
        )

        # Execute single tick
        record = engine.capture_once(force=True)

        assert record is not None
        assert record.app_name == "code.exe"
        assert record.metadata.get("is_spatially_masked") is True
        assert "discord.exe" in record.metadata.get("spatial_masked_windows", [])

        # Check that saved screenshot exists and is the cropped window of code.exe (Discord region is completely excluded)
        assert record.screenshot_path is not None
        with Image.open(record.screenshot_path) as saved_img:
            assert saved_img.width <= 400, f"Expected cropped window (width<=400), got {saved_img.size}"


def test_spatial_rescue_when_clicking_discord_in_windowed_mode():
    """
    Verify Dilemma A solution (Spatial Rescue):
    When the user clicks inside Discord in windowed mode (covering 40% screen),
    the frame is NOT dropped: Discord is masked, and VS Code (topmost allowed) is captured!
    """
    rules = {
        "mode": "blocklist",
        "action_on_block": "drop",
        "blocked_apps": ["discord.exe"],
    }
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f_rules:
        json.dump(rules, f_rules)
        rule_path = f_rules.name

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        screenshots_dir = Path(tmpdir) / "screenshots"

        cfg = AppConfig()
        cfg.privacy.config_path = rule_path
        cfg.storage.database_path = str(db_path)
        cfg.storage.screenshots_dir = str(screenshots_dir)
        cfg.ocr.enabled = False

        engine = CaptureEngine(config=cfg)

        mock_img = Image.new("RGB", (1000, 600), color=(255, 255, 255))
        engine.capturer.capture = MagicMock(return_value=mock_img)
        engine.capturer.last_capture_origin = (0, 0)

        # User clicked inside Discord! Active window is discord.exe (occupying 40% on right)
        engine.context_extractor.get_active_context = MagicMock(
            return_value=WindowContext(
                hwnd=20, process_id=2002, app_name="discord.exe", window_title="Discord", bounding_box=(600, 0, 1000, 600)
            )
        )

        # Both Discord and VS Code are visible side-by-side
        engine.context_extractor.get_visible_windows = MagicMock(
            return_value=[
                VisibleWindow(hwnd=20, process_id=2002, app_name="discord.exe", window_title="Discord", bounding_box=(600, 0, 1000, 600)),
                VisibleWindow(hwnd=10, process_id=1001, app_name="code.exe", window_title="main.py", bounding_box=(0, 0, 600, 600)),
            ]
        )

        record = engine.capture_once(force=True)

        # The frame should NOT be dropped! It was rescued by promoting code.exe while masking discord!
        assert record is not None
        assert record.app_name == "code.exe"
        assert record.metadata.get("is_spatially_masked") is True
        assert "discord.exe" in record.metadata.get("spatial_masked_windows", [])


def test_full_screen_blocked_app_drops():
    """Verify that if Discord is maximized (covering >= 85% of screen), the frame is dropped."""
    rules = {
        "mode": "blocklist",
        "action_on_block": "drop",
        "blocked_apps": ["discord.exe"],
    }
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f_rules:
        json.dump(rules, f_rules)
        rule_path = f_rules.name

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        screenshots_dir = Path(tmpdir) / "screenshots"

        cfg = AppConfig()
        cfg.privacy.config_path = rule_path
        cfg.storage.database_path = str(db_path)
        cfg.storage.screenshots_dir = str(screenshots_dir)
        cfg.ocr.enabled = False

        engine = CaptureEngine(config=cfg)

        mock_img = Image.new("RGB", (1000, 600), color=(255, 255, 255))
        engine.capturer.capture = MagicMock(return_value=mock_img)
        engine.capturer.last_capture_origin = (0, 0)

        # Discord is maximized covering the whole screen
        engine.context_extractor.get_active_context = MagicMock(
            return_value=WindowContext(
                hwnd=20, process_id=2002, app_name="discord.exe", window_title="Discord", bounding_box=(0, 0, 1000, 600)
            )
        )
        engine.context_extractor.get_visible_windows = MagicMock(
            return_value=[
                VisibleWindow(hwnd=20, process_id=2002, app_name="discord.exe", window_title="Discord", bounding_box=(0, 0, 1000, 600)),
            ]
        )

        record = engine.capture_once(force=True)
        # Should be completely dropped
        assert record is None
