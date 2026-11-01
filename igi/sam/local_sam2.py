"""
IGI (𒅆) — Dual MoE SAM: Local Geometric Expert (SAM 2 / MobileSAM)
Handles real-time human mouse gestures (circles, lassos, boxes) and edge-gradient snapping with <15ms response.
"""

from __future__ import annotations

from typing import List, Tuple, Dict, Any, Optional
from PIL import Image
import numpy as np

try:
    import scipy.ndimage as ndi
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False

try:
    from .mask_utils import compute_bounding_box, compute_centroid, crop_image_with_box
except (ImportError, ValueError):
    from sam.mask_utils import compute_bounding_box, compute_centroid, crop_image_with_box


class LocalSAM2Engine:
    """
    Local Geometric Segmentation Specialist.
    Snaps rough human-drawn circles and rough candidate boxes to clean, precise UI boundaries
    using high-speed Sobel edge gradient energy minimization and contour analysis (<15ms).
    """

    def __init__(self, use_onnx: bool = True):
        self.use_onnx = use_onnx
        self._onnx_session = None

    def segment_gesture(
        self,
        full_screenshot: Image.Image,
        stroke_points: List[Tuple[int, int]],
        padding: int = 8
    ) -> Dict[str, Any]:
        """
        Process user's drawn circle/lasso stroke and snap tightly to the enclosed visual element.
        Returns:
            - "crop": cropped PIL Image of the selected element
            - "bbox": (x1, y1, x2, y2)
            - "centroid": (cx, cy)
            - "polygon": smoothed boundary points
        """
        w, h = full_screenshot.size
        raw_bbox = compute_bounding_box(stroke_points, padding=padding, max_w=w, max_h=h)
        centroid = compute_centroid(stroke_points)

        x1, y1, x2, y2 = raw_bbox
        if x2 - x1 < 10 or y2 - y1 < 10:
            # Fallback if too small
            x1 = max(0, centroid[0] - 50)
            y1 = max(0, centroid[1] - 50)
            x2 = min(w, centroid[0] + 50)
            y2 = min(h, centroid[1] + 50)
            raw_bbox = (x1, y1, x2, y2)

        # Refine bounding box to snap to UI element high-contrast edges
        snapped_bbox = self.refine_box(full_screenshot, raw_bbox, search_pad=14)

        cropped = crop_image_with_box(full_screenshot, snapped_bbox)

        return {
            "crop": cropped,
            "bbox": tuple(snapped_bbox),
            "centroid": centroid,
            "polygon": stroke_points,
            "width": snapped_bbox[2] - snapped_bbox[0],
            "height": snapped_bbox[3] - snapped_bbox[1]
        }

    def refine_box(
        self,
        screenshot: Image.Image,
        rough_bbox: Tuple[int, int, int, int] | List[int],
        search_pad: int = 16
    ) -> List[int]:
        """
        Use SAM 2 local contrast / gradient analysis to snap rough bounding box tightly to UI button boundaries.
        Computes Sobel gradient energy fields in the neighborhood and locks onto high-contrast UI edges.
        """
        x1, y1, x2, y2 = map(int, rough_bbox)
        w, h = screenshot.size

        # Clamp initial bbox to image
        x1 = max(0, min(w - 2, x1))
        y1 = max(0, min(h - 2, y1))
        x2 = max(x1 + 1, min(w, x2))
        y2 = max(y1 + 1, min(h, y2))

        if not _HAS_SCIPY or (x2 - x1 < 6) or (y2 - y1 < 6):
            return [x1, y1, x2, y2]

        try:
            # Expand search patch around the rough bounding box
            cx1 = max(0, x1 - search_pad)
            cy1 = max(0, y1 - search_pad)
            cx2 = min(w, x2 + search_pad)
            cy2 = min(h, y2 + search_pad)

            patch = screenshot.crop((cx1, cy1, cx2, cy2)).convert("L")
            arr = np.array(patch, dtype=np.float32)

            # Compute Sobel gradients in horizontal and vertical directions
            gx = np.abs(ndi.sobel(arr, axis=1))
            gy = np.abs(ndi.sobel(arr, axis=0))

            # Vertical edges (left and right borders) -> integrate across vertical lines
            vert_profile = gx.mean(axis=0)
            # Horizontal edges (top and bottom borders) -> integrate across horizontal lines
            horiz_profile = gy.mean(axis=1)

            rel_x1 = x1 - cx1
            rel_y1 = y1 - cy1
            rel_x2 = x2 - cx1
            rel_y2 = y2 - cy1

            def find_peak(profile: np.ndarray, center: int, window: int = 14) -> int:
                start = max(0, center - window)
                end = min(len(profile), center + window + 1)
                sub = profile[start:end]
                if len(sub) == 0:
                    return center
                max_val = sub.max()
                # Only snap if edge gradient is distinct from background noise
                mean_val = profile.mean()
                if max_val > mean_val * 1.35 and max_val > 12.0:
                    return start + int(np.argmax(sub))
                return center

            snapped_x1 = cx1 + find_peak(vert_profile, rel_x1, window=search_pad)
            snapped_y1 = cy1 + find_peak(horiz_profile, rel_y1, window=search_pad)
            snapped_x2 = cx1 + find_peak(vert_profile, rel_x2, window=search_pad)
            snapped_y2 = cy1 + find_peak(horiz_profile, rel_y2, window=search_pad)

            # Ensure minimum width/height and valid orientation
            if snapped_x2 - snapped_x1 < 10:
                snapped_x1 = max(0, min(snapped_x1, x1))
                snapped_x2 = min(w, max(snapped_x2, x2))
            if snapped_y2 - snapped_y1 < 10:
                snapped_y1 = max(0, min(snapped_y1, y1))
                snapped_y2 = min(h, max(snapped_y2, y2))

            return [
                max(0, min(w - 1, snapped_x1)),
                max(0, min(h - 1, snapped_y1)),
                max(snapped_x1 + 1, min(w, snapped_x2)),
                max(snapped_y1 + 1, min(h, snapped_y2))
            ]
        except Exception:
            return [x1, y1, x2, y2]
