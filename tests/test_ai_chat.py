"""
Unit tests for AI Chat and MCP Server integration.
"""

import tempfile
from pathlib import Path
from memvision.storage import CaptureRecord, MemoryStorage
from memvision.ai_chat import AIChatEngine
from memvision.mcp_server import MCPServer
from memvision.config import AppConfig


def test_ai_chat_and_mcp_retrieval():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_memory.db"
        storage = MemoryStorage(db_path=db_path)

        # Seed sample memories
        storage.save_capture(CaptureRecord(
            app_name="brave.exe",
            window_title="Meta Model API Documentation - Overview",
            url="https://dev.meta.ai/docs/overview",
            ocr_text="Build multimodal AI applications using Meta Model API with Muse Code and Llama 3.",
            phash="1111222233334444",
        ))

        storage.save_capture(CaptureRecord(
            app_name="code.exe",
            window_title="memvision - Visual Studio Code",
            url=None,
            ocr_text="class ScreenCapturer: def capture(self): pass",
            phash="5555666677778888",
        ))

        # 1. Test AIChatEngine retrieval
        config = AppConfig()
        config.storage.database_path = str(db_path)
        chat = AIChatEngine(config=config, storage=storage)

        retrieved = chat.retrieve_context("Meta Model API", limit=3)
        assert len(retrieved) >= 1
        assert "meta.ai" in (retrieved[0].url or "")

        # Test local fallback response (isolated from live network)
        chat.get_api_credentials = lambda: {"provider": None, "api_key": "", "model": "local", "base_url": ""}
        resp = chat.ask("What was that Meta Model API link?")
        assert len(resp.citations) >= 1
        assert "dev.meta.ai" in resp.answer

        # 2. Test MCP Server tool definitions & execution
        mcp = MCPServer(db_path=str(db_path))
        tools = mcp.get_tool_definitions()
        assert len(tools) == 4
        tool_names = [t["name"] for t in tools]
        assert "search_desktop_memory" in tool_names
        assert "get_recent_memory" in tool_names

        # Execute search tool
        results = mcp.handle_tool_call("search_desktop_memory", {"query": "Meta", "limit": 2})
        assert len(results) >= 1
        assert results[0]["app_name"] == "brave.exe"


if __name__ == "__main__":
    test_ai_chat_and_mcp_retrieval()
    print("All AI Chat and MCP tests passed!")
