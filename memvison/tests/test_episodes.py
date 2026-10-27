"""
Unit tests for Option B: Scene & Episode Clustering.
Validates session grouping, app transitions, idle timeout splits, and MCP/REST endpoints.
"""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from memvision.mcp_server import MCPServer
from memvision.storage import CaptureRecord, MemoryStorage


def test_episode_clustering_and_session_search():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_episodes.db"
        storage = MemoryStorage(db_path=db_path)

        t0 = datetime(2026, 10, 27, 10, 0, 0, tzinfo=timezone.utc)

        # 1. First session in VS Code (3 frames over 2 minutes)
        r1 = CaptureRecord(
            timestamp=t0.isoformat(),
            app_name="code.exe",
            window_title="memvision - storage.py",
            url=None,
            ocr_text="class MemoryStorage: pass",
            phash="1111111111111111",
        )
        storage.save_capture(r1)

        r2 = CaptureRecord(
            timestamp=(t0 + timedelta(seconds=45)).isoformat(),
            app_name="code.exe",
            window_title="memvision - storage.py (modified)",
            url=None,
            ocr_text="def cluster_or_create_episode(): pass",
            phash="1111111111112222",
        )
        storage.save_capture(r2)

        r3 = CaptureRecord(
            timestamp=(t0 + timedelta(seconds=90)).isoformat(),
            app_name="code.exe",
            window_title="memvision - test_episodes.py",
            url=None,
            ocr_text="def test_episodes(): pass",
            phash="1111111111113333",
        )
        storage.save_capture(r3)

        # All 3 frames should be clustered into Episode #1
        episodes = storage.get_episodes()
        assert len(episodes) == 1
        ep1 = episodes[0]
        assert ep1.id == 1
        assert ep1.app_name == "code.exe"
        assert ep1.capture_count == 3
        assert ep1.duration_seconds == 90
        assert "storage" in ep1.summary_keywords.lower()

        # 2. Switch app to Brave browser (creates Episode #2)
        r4 = CaptureRecord(
            timestamp=(t0 + timedelta(seconds=120)).isoformat(),
            app_name="brave.exe",
            window_title="SQLite WAL Mode - Documentation",
            url="https://sqlite.org/wal.html",
            ocr_text="Write-Ahead Logging provides concurrency.",
            phash="4444444444444444",
        )
        storage.save_capture(r4)

        episodes = storage.get_episodes()
        assert len(episodes) == 2
        assert episodes[0].app_name == "brave.exe"
        assert episodes[0].url == "https://sqlite.org/wal.html"
        assert episodes[1].app_name == "code.exe"

        # 3. Idle gap (> 180s) in Brave creates Episode #3
        r5 = CaptureRecord(
            timestamp=(t0 + timedelta(seconds=600)).isoformat(),
            app_name="brave.exe",
            window_title="Meta Hackathon Overview",
            url="https://hackathon.meta.com",
            ocr_text="Build open-source AI applications.",
            phash="5555555555555555",
        )
        storage.save_capture(r5)

        episodes = storage.get_episodes()
        assert len(episodes) == 3

        # 4. Test episode search
        found_code = storage.search_episodes("code")
        assert len(found_code) == 1
        assert found_code[0].app_name == "code.exe"

        found_sqlite = storage.search_episodes("sqlite")
        assert len(found_sqlite) >= 1

        # 5. Test MCP Server get_activity_sessions
        mcp = MCPServer(db_path=str(db_path))
        sessions_result = mcp.handle_tool_call("get_activity_sessions", {"limit": 5})
        assert len(sessions_result) == 3
        assert sessions_result[0]["app_name"] in ("brave.exe", "code.exe")
        assert "duration_minutes" in sessions_result[0]


if __name__ == "__main__":
    test_episode_clustering_and_session_search()
    print("All Episode clustering tests passed!")
