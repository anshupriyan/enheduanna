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

        # 7. Test app_name filtering
        chrome_only = storage.search(app_name="chrome.exe")
        assert len(chrome_only) == 1
        assert chrome_only[0].app_name == "chrome.exe"

        code_only = storage.search(app_name="code.exe")
        assert len(code_only) == 1
        assert code_only[0].app_name == "code.exe"

        # 8. Test combined keyword and app_name filter
        filtered_search = storage.search("privacy-first", app_name="chrome.exe")
        assert len(filtered_search) == 1
        assert filtered_search[0].id == id1

        # Negative filter test: keyword in chrome record, but filtered to code.exe
        no_match = storage.search("privacy-first", app_name="code.exe")
        assert len(no_match) == 0

        # 9. Check stats
        stats = storage.get_stats()
        assert stats["total_captures"] == 2
        assert stats["redacted_captures"] == 0
        assert stats["database_size_bytes"] > 0


def test_storage_file_path_and_url_sanitization():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_path_sanitization.db"
        storage = MemoryStorage(db_path=db_path, enable_fts=True)

        rec = CaptureRecord(
            app_name="code.exe",
            window_title="memvison - Antigravity IDE - README.md",
            file_path=r"C:\meta hackathon\memvison\README.md",
            url="https://accounts.google.com/o/oauth2/auth?client_id=myclient&state=leaked_oauth_state_12345678",
            ocr_text="Documentation for memvision memory capture.",
        )
        rec_id = storage.save_capture(rec)
        assert rec_id > 0

        # Retrieve and verify file_path
        fetched = storage.get_by_id(rec_id)
        assert fetched is not None
        assert fetched.file_path == r"C:\meta hackathon\memvison\README.md"

        # Search by file_path
        results = storage.search(file_path="README.md")
        assert len(results) == 1
        assert results[0].id == rec_id

        # Retroactive sanitization purges leaked OAuth state from URL
        from memvision.privacy import PrivacyGatekeeper
        gate = PrivacyGatekeeper(enabled=True)
        res_san = storage.sanitize_database(privacy_gate=gate)
        assert res_san["records_sanitized"] >= 1

        sanitized_rec = storage.get_by_id(rec_id)
        assert "leaked_oauth_state_12345678" not in sanitized_rec.url
        assert "[REDACTED_OAUTH_STATE]" in sanitized_rec.url
        assert sanitized_rec.is_redacted == 1


if __name__ == "__main__":
    test_storage_crud_and_fts()
    test_storage_file_path_and_url_sanitization()
    print("All Storage tests passed!")

