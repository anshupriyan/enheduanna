"""
IGI (𒅆) — Configuration & Localhost Discovery
Reads settings from enheduanna.config.json and environment.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CoreServerConfig:
    host: str = "127.0.0.1"
    port: int = 4100

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass
class ModelConfig:
    provider: str = "meta"
    tool_model: str = "muse-spark-1.3"
    synthesis_model: str = "muse-wonder-1.0"
    base_url: str = "https://api.meta.ai/v1"
    api_key: str = ""


@dataclass
class SpatialConfig:
    """Local spatial grounding configuration (Sobel gradient snapping + WinRT Optical OCR)."""
    enable_local_geometry: bool = True
    enable_optical_ocr: bool = True
    enable_projections: bool = False
    min_selection_pixels: int = 16  # minimum bounding box size

    # Backwards compatibility accessors
    @property
    def enable_local_sam2(self) -> bool:
        return self.enable_local_geometry

    @property
    def enable_cloud_sam3(self) -> bool:
        return False

# Backwards compatibility alias
SAMConfig = SpatialConfig


@dataclass
class HUDConfig:
    width: int = 440
    height: int = 600
    margin_bottom: int = 36
    margin_right: int = 36
    hotkey: str = "<ctrl>+<shift>+q"
    accent_color: str = "#f59e0b"  # Sumerian amber gold
    bg_color: str = "#0d0f12"      # Deep obsidian
    border_color: str = "#262b36"  # Subtle slate
    acrylic_opacity: float = 0.94


@dataclass
class IgiConfig:
    server: CoreServerConfig = field(default_factory=CoreServerConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    sam: SAMConfig = field(default_factory=SAMConfig)
    hud: HUDConfig = field(default_factory=HUDConfig)


def find_enheduanna_config() -> Optional[Path]:
    """Search for enheduanna.config.json upwards from current file."""
    current = Path(__file__).resolve().parent
    for _ in range(4):
        cfg_path = current / "enheduanna.config.json"
        if cfg_path.exists():
            return cfg_path
        current = current.parent
    return None


def load_config() -> IgiConfig:
    """Load configuration merging enheduanna.config.json with environment defaults."""
    config = IgiConfig()
    cfg_file = find_enheduanna_config()

    if cfg_file and cfg_file.exists():
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            if "server" in data:
                srv = data["server"]
                config.server.host = srv.get("host", config.server.host)
                config.server.port = srv.get("port", config.server.port)

            if "model" in data:
                mdl = data["model"]
                config.model.provider = mdl.get("provider", config.model.provider)
                config.model.tool_model = mdl.get("toolModel", config.model.tool_model)
                config.model.synthesis_model = mdl.get("synthesisModel", config.model.synthesis_model)
                config.model.base_url = mdl.get("baseUrl", config.model.base_url)
                config.model.api_key = mdl.get("apiKey", os.getenv("META_API_KEY", ""))

            if "spatial" in data:
                sp_data = data["spatial"]
                config.sam.enable_local_geometry = sp_data.get("enableLocalGeometry", config.sam.enable_local_geometry)
                config.sam.enable_optical_ocr = sp_data.get("enableOpticalOcr", config.sam.enable_optical_ocr)
                config.sam.min_selection_pixels = sp_data.get("minSelectionPixels", config.sam.min_selection_pixels)
            elif "sam" in data:
                sam_data = data["sam"]
                config.sam.enable_local_geometry = sam_data.get("enableLocalSam2", config.sam.enable_local_geometry)

        except Exception as e:
            print(f"[IGI Config] Warning: Failed to parse {cfg_file}: {e}")

    # Fallback to env overrides
    env_port = os.getenv("ENHEDUANNA_PORT")
    if env_port:
        try:
            config.server.port = int(env_port)
        except ValueError:
            pass

    env_key = os.getenv("META_API_KEY")
    if env_key:
        config.model.api_key = env_key

    return config

