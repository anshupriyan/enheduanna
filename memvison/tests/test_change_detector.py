"""
Unit tests for ChangeDetector and Perceptual Hashing.
"""

from PIL import Image, ImageDraw
from memvision.change_detector import ChangeDetector


def test_change_detector_identical_frames():
    detector = ChangeDetector(threshold=3, algorithm="dhash")

    img1 = Image.new("RGB", (300, 200), color=(120, 120, 120))
    img2 = Image.new("RGB", (300, 200), color=(120, 120, 120))

    # First frame is always considered a change/baseline
    has_changed1, dist1, _ = detector.evaluate_change(img1)
    assert has_changed1

    # Second identical frame should have distance 0 and not trigger change
    has_changed2, dist2, _ = detector.evaluate_change(img2)
    assert not has_changed2
    assert dist2 == 0


def test_change_detector_meaningful_difference():
    detector = ChangeDetector(threshold=3, algorithm="dhash")

    # Frame 1: Blank gray
    img1 = Image.new("RGB", (400, 400), color=(50, 50, 50))
    detector.evaluate_change(img1)

    # Frame 2: Distinct pattern with large contrasting rectangles
    img2 = Image.new("RGB", (400, 400), color=(250, 250, 250))
    draw = ImageDraw.Draw(img2)
    draw.rectangle([0, 0, 200, 400], fill=(0, 0, 0))

    has_changed, dist, _ = detector.evaluate_change(img2)
    assert has_changed
    assert dist > 3


def test_change_detector_cursor_blink_tolerance():
    detector = ChangeDetector(threshold=3, algorithm="dhash")

    # Frame 1: Large screen
    img1 = Image.new("RGB", (1000, 1000), color=(200, 200, 200))
    detector.evaluate_change(img1)

    # Frame 2: Tiny 2-pixel black line representing a cursor blink
    img2 = img1.copy()
    draw = ImageDraw.Draw(img2)
    draw.line([(500, 500), (500, 515)], fill=(0, 0, 0), width=1)

    has_changed, dist, _ = detector.evaluate_change(img2)
    # Cursor blink on a full-size frame should produce distance 0 or <= threshold
    assert not has_changed
    assert dist <= 3


if __name__ == "__main__":
    test_change_detector_identical_frames()
    test_change_detector_meaningful_difference()
    test_change_detector_cursor_blink_tolerance()
    print("All ChangeDetector tests passed!")
