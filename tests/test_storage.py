"""
Unit tests for MemoryStorage with SQLite and FTS5 search.
"""

import tempfile
from pathlib import Path
from memvision.storage import CaptureRecord, MemoryStorage


def test_storage_crud_and_fts():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_memory.db"
        storage = MemoryStorage(db_path=db_path, enable_fts=True)

        # 1. Insert records
        r1 = CaptureRecord(
            app_name="chrome.exe",
            window_title="Meta Hackathon AI Guidelines - Documentation",
            url="https://hackathon.meta.com/guidelines",
            ocr_text="Building local memory layer with privacy-first architecture and WinRT OCR.",
            phash="0011223344556677",
            width=1920,
            height=1080,
        )
        id1 = storage.save_capture(r1)
        assert id1 > 0

        r2 = CaptureRecord(
            app_name="code.exe",
            window_title="mem-vision-mcp - Visual Studio Code",
            url=None,
            ocr_text="def compute_hash(img): return imagehash.dhash(img)",
            phash="8899aabbccddeeff",
            width=1920,
            height=1080,
        )
        id2 = storage.save_capture(r2)
        assert id2 > id1

        # 2. Get by ID
        fetched1 = storage.get_by_id(id1)
        assert fetched1 is not None
        assert fetched1.app_name == "chrome.exe"
        assert fetched1.url == "https://hackathon.meta.com/guidelines"

        # 3. Recent records
        recent = storage.get_recent(limit=5)
        assert len(recent) == 2
        assert recent[0].id == id2

        # 4. Search query by keyword in OCR text
        ocr_results = storage.search("privacy-first")
        assert len(ocr_results) >= 1
        assert ocr_results[0].id == id1

        # 5. Search query by window title keyword
        title_results = storage.search("Guidelines")
        assert len(title_results) >= 1
        assert title_results[0].id == id1

        # 6. Search query by code keyword
        code_results = storage.search("compute_hash")
        assert len(code_results) >= 1
        assert code_results[0].id == id2

        # 7. Check stats
        stats = storage.get_stats()
        assert stats["total_captures"] == 2
        assert stats["redacted_captures"] == 0
        assert stats["database_size_bytes"] > 0


if __name__ == "__main__":
    test_storage_crud_and_fts()
    print("All Storage tests passed!")
