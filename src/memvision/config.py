"""
Configuration management for mem-vision-mcp.
Supports JSON configuration files with typed dataclasses and sensible defaults.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CaptureConfig:
    interval_seconds: float = 1.0
    hash_threshold: int = 3
    hash_algorithm: str = "dhash"       # "dhash", "phash", "ahash"
    image_format: str = "jpeg"          # "jpeg" or "webp"
    image_quality: int = 80
    ocr_max_dimension: int = 0          # 0 = 100% full native resolution for OCR
    storage_max_dimension: int = 1280   # Max dimension for saved screenshot (e.g. 720p/1280px)
    monitor_mode: str = "all"           # "all" (all displays) or "primary" (primary display)
    capture_active_window_only: bool = False
    max_dimension: int = 0              # Backwards-compatible alias


@dataclass
class OCRConfig:
    primary_engine: str = "winrt"  # "winrt" (Windows native) or "pytesseract"
    fallback_engine: str = "pytesseract"
    enabled: bool = True
    confidence_threshold: float = 0.0


@dataclass
class StorageConfig:
    database_path: str = "data/memvision.db"
    screenshots_dir: str = "data/screenshots"
    enable_fts: bool = True
    retention_days: int = 30


@dataclass
class PrivacyConfig:
    config_path: str = "config/privacy_rules.json"
    enabled: bool = True


@dataclass
class AIConfig:
    provider: str = "meta"                  # "meta", "openai", "ollama", "custom"
    base_url: str = "https://api.meta.ai/v1"
    api_key_env: str = "META_API_KEY"
    model: str = "llama-3.3-70b-instruct"
    temperature: float = 0.2
    max_tokens: int = 1024
    max_context_items: int = 6


@dataclass
class AppConfig:
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    ocr: OCRConfig = field(default_factory=OCRConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    ai: AIConfig = field(default_factory=AIConfig)

    @classmethod
    def from_json(cls, config_path: str | Path) -> AppConfig:
        """Load configuration from a JSON file, falling back to defaults for missing keys."""
        path = Path(config_path)
        if not path.is_file():
            logger.warning("Config file %s not found. Using default settings.", path)
            return cls()

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            capture_data = data.get("capture", {})
            ocr_data = data.get("ocr", {})
            storage_data = data.get("storage", {})
            privacy_data = data.get("privacy", {})
            ai_data = data.get("ai", {})

            return cls(
                capture=CaptureConfig(**capture_data),
                ocr=OCRConfig(**ocr_data),
                storage=StorageConfig(**storage_data),
                privacy=PrivacyConfig(**privacy_data),
                ai=AIConfig(**ai_data),
            )
        except Exception as e:
            logger.error("Failed to parse config file %s: %s. Using defaults.", path, e)
            return cls()


def load_config(config_path: Optional[str | Path] = None) -> AppConfig:
    """Convenience helper to load AppConfig from path or default location."""
    if config_path:
        return AppConfig.from_json(config_path)

    default_path = Path("config/default_config.json")
    if default_path.is_file():
        return AppConfig.from_json(default_path)

    return AppConfig()
