"""
mem-vision-mcp: A local-first, privacy-first continuous desktop memory layer.
Captures screen context, understands UI structure, and exposes memory via MCP tools for AI agents.
"""

__version__ = "0.1.0"
__author__ = "mem-vision-mcp contributors"
__license__ = "MIT"

from memvision.config import AppConfig, load_config
from memvision.privacy import PrivacyGatekeeper, PrivacyDecision
from memvision.capture import ScreenCapturer
from memvision.change_detector import ChangeDetector
from memvision.context import ContextExtractor, WindowContext
from memvision.ocr import LocalOCREngine
from memvision.storage import MemoryStorage, CaptureRecord
from memvision.engine import CaptureEngine

__all__ = [
    "AppConfig",
    "load_config",
    "PrivacyGatekeeper",
    "PrivacyDecision",
    "ScreenCapturer",
    "ChangeDetector",
    "ContextExtractor",
    "WindowContext",
    "LocalOCREngine",
    "MemoryStorage",
    "CaptureRecord",
    "CaptureEngine",
]
