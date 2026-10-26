"""
Unit tests for the Web UI Server and REST API endpoints.
"""

import json
import socket
import threading
import time
from http.client import HTTPConnection
from pathlib import Path

from memvision.config import AppConfig
from memvision.storage import CaptureRecord, MemoryStorage
from memvision.web_server import MemVisionRequestHandler, ThreadingHTTPServer


def get_free_port():
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def test_web_server_endpoints(tmp_path):
    db_path = tmp_path / "web_test.db"
    storage = MemoryStorage(db_path=db_path)

    # Seed test capture
    rec = CaptureRecord(
        app_name="code.exe",
        window_title="memvision - Visual Studio Code",
        url=None,
        ocr_text="export function testDashboard() { return true; }",
        phash="1234567890abcdef",
    )
    storage.save_capture(rec)

    config = AppConfig()
    config.storage.database_path = str(db_path)

    # Configure handler
    from memvision.ai_chat import AIChatEngine
    chat = AIChatEngine(config=config, storage=storage)
    chat.get_api_credentials = lambda: {"provider": None, "api_key": "", "model": "local", "base_url": ""}

    MemVisionRequestHandler.config = config
    MemVisionRequestHandler.storage = storage
    MemVisionRequestHandler.chat_engine = chat

    port = get_free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), MemVisionRequestHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.2)

    try:
        conn = HTTPConnection("127.0.0.1", port, timeout=5)

        # 1. Test GET / (HTML)
        conn.request("GET", "/")
        resp = conn.getresponse()
        assert resp.status == 200
        html = resp.read().decode("utf-8")
        assert "mem-vision" in html
        assert "capture-modal" in html

        # 2. Test GET /styles.css
        conn.request("GET", "/styles.css")
        resp = conn.getresponse()
        assert resp.status == 200
        css = resp.read().decode("utf-8")
        assert "--bg-dark" in css

        # 3. Test GET /app.js
        conn.request("GET", "/app.js")
        resp = conn.getresponse()
        assert resp.status == 200
        js = resp.read().decode("utf-8")
        assert "fetchCaptures" in js

        # 4. Test GET /api/stats
        conn.request("GET", "/api/stats")
        resp = conn.getresponse()
        assert resp.status == 200
        stats = json.loads(resp.read().decode("utf-8"))
        assert stats["total_captures"] == 1

        # 5. Test GET /api/recent
        conn.request("GET", "/api/recent?limit=10")
        resp = conn.getresponse()
        assert resp.status == 200
        recent = json.loads(resp.read().decode("utf-8"))
        assert len(recent) == 1
        assert recent[0]["app_name"] == "code.exe"

        # 6. Test GET /api/search
        conn.request("GET", "/api/search?q=testDashboard")
        resp = conn.getresponse()
        assert resp.status == 200
        search_results = json.loads(resp.read().decode("utf-8"))
        assert len(search_results) == 1

        # 7. Test GET /api/capture/1
        conn.request("GET", "/api/capture/1")
        resp = conn.getresponse()
        assert resp.status == 200
        detail = json.loads(resp.read().decode("utf-8"))
        assert detail["id"] == 1
        assert "testDashboard" in detail["full_ocr_text"]

        # 8. Test POST /api/chat
        body = json.dumps({"query": "What function was written in code?"})
        conn.request("POST", "/api/chat", body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        assert resp.status == 200
        chat_resp = json.loads(resp.read().decode("utf-8"))
        assert "answer" in chat_resp
        assert len(chat_resp["citations"]) >= 1

    finally:
        server.shutdown()
        server.server_close()
