"""
IGI (𒅆) — SAM Mask & Spatial Geometry Utilities
Polygons, bounding boxes, alpha masks, and neon glowing contour rendering.
"""

from __future__ import annotations

import math
from typing import List, Tuple, Optional
from PIL import Image, ImageDraw, ImageFilter
import numpy as np


def compute_bounding_box(points: List[Tuple[int, int]], padding: int = 8, max_w: int = 9999, max_h: int = 9999) -> Tuple[int, int, int, int]:
    """Calculate padded bounding box [x1, y1, x2, y2] from a list of mouse stroke coordinates."""
    if not points:
        return (0, 0, 0, 0)

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]

    x1 = max(0, min(xs) - padding)
    y1 = max(0, min(ys) - padding)
    x2 = min(max_w, max(xs) + padding)
    y2 = min(max_h, max(ys) + padding)

    return (int(x1), int(y1), int(x2), int(y2))


def compute_centroid(points: List[Tuple[int, int]]) -> Tuple[int, int]:
    """Compute centroid point from a stroke loop."""
    if not points:
        return (0, 0)
    avg_x = sum(p[0] for p in points) / len(points)
    avg_y = sum(p[1] for p in points) / len(points)
    return (int(avg_x), int(avg_y))


def crop_image_with_box(image: Image.Image, box: Tuple[int, int, int, int]) -> Image.Image:
    """Crop image to bounding box [x1, y1, x2, y2]."""
    x1, y1, x2, y2 = box
    if x2 <= x1 or y2 <= y1:
        return image.copy()
    return image.crop((x1, y1, x2, y2))


def render_neon_glow_mask(
    base_image: Image.Image,
    polygon: List[Tuple[int, int]],
    color: Tuple[int, int, int] = (245, 158, 11),  # Amber gold
    alpha: int = 60,
    outline_width: int = 3
) -> Image.Image:
    """
    Render a semi-transparent glowing mask over base_image with anti-aliased neon border.
    Returns composite RGBA image.
    """
    canvas = base_image.convert("RGBA")
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    if len(polygon) >= 3:
        # Fill polygon
        draw.polygon(polygon, fill=(*color, alpha))
        # Outline with neon glow
        draw.line(polygon + [polygon[0]], fill=(*color, 230), width=outline_width, joint="curve")

    return Image.alpha_composite(canvas, overlay)

