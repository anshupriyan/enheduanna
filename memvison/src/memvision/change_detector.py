"""
Perceptual Hashing and Visual Change Detection for mem-vision-mcp.
Detects meaningful UI transitions while ignoring static screens and minor cursor blinks.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple
import imagehash
from PIL import Image

logger = logging.getLogger(__name__)


class ChangeDetector:
    """
    Perceptual hash-based change detector.
    Uses difference hashing (dhash) or perceptual hashing (phash) to compare consecutive frames.
    """

    def __init__(self, threshold: int = 3, algorithm: str = "dhash", hash_size: int = 8):
        """
        Args:
            threshold: Maximum Hamming distance to consider two frames identical.
                       Threshold of 2-3 ignores cursor blinks and subpixel antialiasing.
            algorithm: 'dhash' (recommended, ~13ms), 'phash' (~300ms DCT), or 'ahash'.
            hash_size: Size of the hash matrix (default 8 -> 64-bit hash).
        """
        self.threshold = threshold
        self.algorithm = algorithm.lower()
        self.hash_size = hash_size
        self._last_hash: Optional[imagehash.ImageHash] = None
        self._total_evaluated: int = 0
        self._total_changed: int = 0

    def compute_hash(self, image: Image.Image) -> imagehash.ImageHash:
        """Compute perceptual hash of the provided PIL Image."""
        if self.algorithm == "dhash":
            return imagehash.dhash(image, hash_size=self.hash_size)
        elif self.algorithm == "phash":
            # Downscale large images first to accelerate DCT computation
            if image.width > 256 or image.height > 256:
                img_small = image.resize((256, 256), Image.Resampling.BILINEAR)
                return imagehash.phash(img_small, hash_size=self.hash_size)
            return imagehash.phash(image, hash_size=self.hash_size)
        elif self.algorithm == "ahash":
            return imagehash.average_hash(image, hash_size=self.hash_size)
        else:
            return imagehash.dhash(image, hash_size=self.hash_size)

    def evaluate_change(self, image: Image.Image) -> Tuple[bool, int, str]:
        """
        Evaluates whether the image has changed meaningfully compared to the last captured frame.

        Returns:
            Tuple of:
                - has_changed (bool): True if change exceeds threshold or first frame.
                - distance (int): Hamming distance between current and last frame.
                - hash_str (str): Hex representation of current perceptual hash.
        """
        self._total_evaluated += 1
        current_hash = self.compute_hash(image)
        hash_str = str(current_hash)

        if self._last_hash is None:
            self._last_hash = current_hash
            self._total_changed += 1
            return True, 64, hash_str

        # Hamming distance (number of differing bits)
        distance = int(current_hash - self._last_hash)
        has_changed = distance > self.threshold

        if has_changed:
            self._last_hash = current_hash
            self._total_changed += 1
            logger.debug("Visual change detected: Hamming distance=%d > threshold=%d", distance, self.threshold)
        else:
            logger.debug("Screen static: Hamming distance=%d <= threshold=%d", distance, self.threshold)

        return has_changed, distance, hash_str

    def reset(self) -> None:
        """Reset internal hash state."""
        self._last_hash = None

    @property
    def stats(self) -> dict:
        """Return operational statistics."""
        return {
            "total_evaluated": self._total_evaluated,
            "total_changed": self._total_changed,
            "suppressed_frames": self._total_evaluated - self._total_changed,
            "suppression_ratio": (
                (self._total_evaluated - self._total_changed) / self._total_evaluated
                if self._total_evaluated > 0 else 0.0
            ),
        }
