"""
Unit tests for Video Suppression & Incremental Draft Collapsing in memvison.
"""

import tempfile
from pathlib import Path
from memvision.config import AppConfig
from memvision.engine import CaptureEngine
from memvision.storage import CaptureRecord, MemoryStorage


def test_evaluate_text_stability_video_playback():
    """Verify that video playback with moving pixels but static text is flagged as video_static."""
    engine = CaptureEngine(AppConfig())

    prev_text = "YouTube - Learn Rust in 100 Seconds - Fireship. 1.2M views, 2 years ago. Comments (412)..."
    # Small video artifact or playback timer change
    curr_text = "YouTube - Learn Rust in 100 Seconds - Fireship. 1.2M views, 2 years ago. Comments (412)... 01:24"

    is_video_static, is_draft, char_sim, containment = engine._evaluate_text_stability(prev_text, curr_text)
    assert is_video_static, f"Expected video_static=True, got False (char_sim={char_sim})"
    assert not is_draft


def test_evaluate_text_stability_fullscreen_video_no_text():
    """Verify that fullscreen video player with empty OCR text is recognized as static video."""
    engine = CaptureEngine(AppConfig())
    is_video_static, is_draft, _, _ = engine._evaluate_text_stability("", "")
    assert is_video_static
    assert not is_draft


def test_evaluate_text_stability_draft_expansion():
    """Verify that incremental paragraph drafting is flagged as draft_expansion."""
    engine = CaptureEngine(AppConfig())

    para_1 = "Chapter 1: The Beginning of the Autonomous Desktop Agent. In this chapter we introduce the memory layer."
    para_1_and_2 = (
        "Chapter 1: The Beginning of the Autonomous Desktop Agent. In this chapter we introduce the memory layer. "
        "Chapter 2: Secure Tool Execution and Granular Policy Sandboxing for CLI commands."
    )

    is_video_static, is_draft, char_sim, containment = engine._evaluate_text_stability(para_1, para_1_and_2)
    assert not is_video_static
    assert is_draft, f"Expected is_draft=True, got False (containment={containment})"
    assert containment >= 0.85


def test_evaluate_text_stability_new_window_or_navigation():
    """Verify that completely different text is treated as a genuine new capture."""
    engine = CaptureEngine(AppConfig())

    page_1 = "Google Search: Best laptops of 2026 for AI development"
    page_2 = "GitHub: anshupriyan/enheduanna - Autonomous desktop scribe and execution agent"

    is_video_static, is_draft, _, _ = engine._evaluate_text_stability(page_1, page_2)
    assert not is_video_static
    assert not is_draft


def test_storage_update_capture_synchronizes_fts():
    """Verify that update_capture updates SQLite record and automatically updates FTS5 index."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_fts.db"
        storage = MemoryStorage(db_path=db_path, enable_fts=True)

        rec = CaptureRecord(
            timestamp="2026-10-27T12:00:00Z",
            app_name="Notepad.exe",
            window_title="proposal.txt - Notepad",
            ocr_text="Paragraph 1: Initial rough draft of Enheduanna proposal.",
            screenshot_path=str(Path(tmpdir) / "shot1.jpg"),
        )
        rec_id = storage.save_capture(rec)

        # FTS search for Paragraph 1
        res = storage.search(query="Initial rough draft")
        assert len(res) == 1
        assert res[0].id == rec_id

        # Update capture with Paragraph 2
        rec.ocr_text = "Paragraph 1: Initial rough draft. Paragraph 2: Comprehensive system architecture."
        rec.screenshot_path = str(Path(tmpdir) / "shot2.jpg")
        success = storage.update_capture(rec_id, rec)
        assert success

        # Verify old text query returns updated content
        res_arch = storage.search(query="Comprehensive system architecture")
        assert len(res_arch) == 1
        assert res_arch[0].id == rec_id
        assert "Paragraph 2" in res_arch[0].ocr_text


if __name__ == "__main__":
    test_evaluate_text_stability_video_playback()
    test_evaluate_text_stability_fullscreen_video_no_text()
    test_evaluate_text_stability_draft_expansion()
    test_evaluate_text_stability_new_window_or_navigation()
    test_storage_update_capture_synchronizes_fts()
    print("All stability tests passed!")
