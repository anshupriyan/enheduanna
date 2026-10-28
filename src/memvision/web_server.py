"""
Web Dashboard and REST API Server for mem-vision-mcp.
Zero-dependency, local-first web server using Python standard library http.server.
Serves the dark-mode glassmorphic dashboard and exposes REST endpoints for
timeline viewing, FTS5 search, full OCR inspection, and AI chat memory synthesis.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from memvision.ai_chat import AIChatEngine
from memvision.config import AppConfig, load_config
from memvision.storage import MemoryStorage

logger = logging.getLogger("web_server")
WEB_DIR = Path(__file__).parent / "web"


class MemVisionRequestHandler(SimpleHTTPRequestHandler):
    """Handles REST API and static web asset requests."""

    storage: MemoryStorage
    chat_engine: AIChatEngine
    config: AppConfig

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query_params = parse_qs(parsed_url.query)

        # Static assets
        if path == "/" or path == "/index.html":
            self._serve_file(WEB_DIR / "index.html", "text/html; charset=utf-8")
        elif path == "/styles.css":
            self._serve_file(WEB_DIR / "styles.css", "text/css; charset=utf-8")
        elif path == "/app.js":
            self._serve_file(WEB_DIR / "app.js", "application/javascript; charset=utf-8")

        # REST API endpoints
        elif path == "/api/stats":
            self._handle_api_stats()
        elif path == "/api/sessions":
            limit = int(query_params.get("limit", ["20"])[0])
            episodes = self.storage.get_episodes(limit=limit)
            self._send_json([ep.to_dict() for ep in episodes])
        elif path == "/api/recent":
            limit = int(query_params.get("limit", ["48"])[0])
            self._handle_api_recent(limit)
        elif path == "/api/search":
            q = query_params.get("q", [""])[0]
            limit = int(query_params.get("limit", ["48"])[0])
            self._handle_api_search(q, limit)
        elif path.startswith("/api/capture/"):
            capture_id_str = path.split("/")[-1]
            try:
                capture_id = int(capture_id_str)
                self._handle_api_capture(capture_id)
            except ValueError:
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid capture ID")
        elif path.startswith("/api/screenshot/"):
            capture_id_str = path.split("/")[-1]
            try:
                capture_id = int(capture_id_str)
                self._handle_api_screenshot(capture_id)
            except ValueError:
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid capture ID")
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        if path == "/api/chat":
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                self.send_error(HTTPStatus.BAD_REQUEST, "Missing request body")
                return

            body_bytes = self.rfile.read(content_length)
            try:
                data = json.loads(body_bytes.decode("utf-8"))
                query = data.get("query", "").strip()
                if not query:
                    self.send_error(HTTPStatus.BAD_REQUEST, "Query cannot be empty")
                    return

                resp = self.chat_engine.ask(query)
                citations = [
                    {
                        "id": c.id,
                        "timestamp": c.timestamp,
                        "app_name": c.app_name,
                        "window_title": c.window_title,
                        "url": c.url,
                    }
                    for c in resp.citations
                ]

                result_json = {
                    "answer": resp.answer,
                    "citations": citations,
                    "model_used": resp.model_used,
                }
                self._send_json(result_json)

            except Exception as e:
                logger.error("Chat API error: %s", e)
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Chat synthesis error: {e}")
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def _handle_api_stats(self) -> None:
        stats = self.storage.get_stats()
        self._send_json(stats)

    def _handle_api_recent(self, limit: int) -> None:
        records = self.storage.get_recent(limit=limit)
        items = [
            {
                "id": r.id,
                "timestamp": r.timestamp,
                "app_name": r.app_name,
                "window_title": r.window_title,
                "file_path": r.file_path,
                "url": r.url,
                "ocr_snippet": r.ocr_text[:280] if r.ocr_text else "",
                "screenshot_path": r.screenshot_path,
                "is_spatially_masked": bool((r.metadata or {}).get("is_spatially_masked")),
                "spatial_masked_windows": (r.metadata or {}).get("spatial_masked_windows", []),
            }
            for r in records
        ]
        self._send_json(items)

    def _handle_api_search(self, query: str, limit: int) -> None:
        if not query.strip():
            self._handle_api_recent(limit)
            return

        records = self.storage.search(query, limit=limit)
        items = [
            {
                "id": r.id,
                "timestamp": r.timestamp,
                "app_name": r.app_name,
                "window_title": r.window_title,
                "file_path": r.file_path,
                "url": r.url,
                "ocr_snippet": r.ocr_text[:280] if r.ocr_text else "",
                "screenshot_path": r.screenshot_path,
                "is_spatially_masked": bool((r.metadata or {}).get("is_spatially_masked")),
                "spatial_masked_windows": (r.metadata or {}).get("spatial_masked_windows", []),
            }
            for r in records
        ]
        self._send_json(items)

    def _handle_api_capture(self, capture_id: int) -> None:
        record = self.storage.get_by_id(capture_id)
        if not record:
            self.send_error(HTTPStatus.NOT_FOUND, f"Capture #{capture_id} not found")
            return

        data = {
            "id": record.id,
            "timestamp": record.timestamp,
            "app_name": record.app_name,
            "window_title": record.window_title,
            "file_path": record.file_path,
            "url": record.url,
            "full_ocr_text": record.ocr_text,
            "phash": record.phash,
            "screenshot_path": record.screenshot_path,
            "metadata": record.metadata,
        }
        self._send_json(data)

    def _handle_api_screenshot(self, capture_id: int) -> None:
        record = self.storage.get_by_id(capture_id)
        if not record or not record.screenshot_path:
            self.send_error(HTTPStatus.NOT_FOUND, "Screenshot not found")
            return

        file_path = Path(record.screenshot_path)
        if not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Screenshot file missing on disk")
            return

        mime_type, _ = mimetypes.guess_type(str(file_path))
        if not mime_type:
            mime_type = "image/jpeg"

        self._serve_file(file_path, mime_type, cache_seconds=86400)

    def _serve_file(self, file_path: Path, content_type: str, cache_seconds: int = 0) -> None:
        try:
            with open(file_path, "rb") as f:
                content = f.read()

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            if cache_seconds > 0:
                self.send_header("Cache-Control", f"public, max-age={cache_seconds}")
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            logger.error("Error serving file %s: %s", file_path, e)
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Error reading file")

    def _send_json(self, data: object) -> None:
        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        # Suppress noisy standard request logging to keep console clean
        logger.debug("%s - - [%s] %s", self.client_address[0], self.log_date_time_string(), format % args)


def run_web_server(config: AppConfig, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    """Initializes and runs the mem-vision-mcp Web UI server."""
    storage = MemoryStorage(config.storage.database_path, config.storage.enable_fts)
    chat_engine = AIChatEngine(config, storage)

    MemVisionRequestHandler.config = config
    MemVisionRequestHandler.storage = storage
    MemVisionRequestHandler.chat_engine = chat_engine

    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, MemVisionRequestHandler)

    url = f"http://{host}:{port}"
    print("=" * 60)
    print("  🌐 mem-vision-mcp Web Dashboard")
    print(f"  • Dashboard URL: {url}")
    print(f"  • SQLite DB:     {config.storage.database_path}")
    print("  Press Ctrl+C to stop the dashboard server.")
    print("=" * 60)

    if open_browser:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception as e:
            logger.warning("Could not open browser automatically: %s", e)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping web dashboard server...")
    finally:
        httpd.server_close()
