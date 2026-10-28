"""
Model Context Protocol (MCP) Server for mem-vision-mcp.
Exposes local desktop memory, OCR search, and context retrieval as MCP tools for AI agents
(compatible with Claude Desktop, Cursor, and any MCP client via JSON-RPC over stdio).
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from PIL import Image, ImageFilter

# Ensure parent directory is in sys.path when executed directly
_src_dir = str(Path(__file__).resolve().parent.parent)
_project_root = Path(__file__).resolve().parent.parent.parent
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from memvision.config import load_config
from memvision.privacy import PrivacyGatekeeper
from memvision.storage import MemoryStorage

# Configure logger to output only to stderr (stdout must be exclusively JSON-RPC messages)
logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="[MCP] %(message)s")
logger = logging.getLogger("mcp_server")


def make_snippet(text: str, query: str = "", max_chars: int = 300) -> str:
    """Extract a concise text snippet centered around the search query."""
    if not text:
        return ""
    clean = " ".join(text.split()).strip()
    if query and query.strip():
        q = query.strip().lower()
        idx = clean.lower().find(q)
        if idx != -1:
            start = max(0, idx - 60)
            end = min(len(clean), idx + len(q) + 140)
            prefix = "..." if start > 0 else ""
            suffix = "..." if end < len(clean) else ""
            return prefix + clean[start:end].strip() + suffix
    return clean[:max_chars].strip() + ("..." if len(clean) > max_chars else "")


class MCPServer:
    """
    Standard MCP (Model Context Protocol) JSON-RPC 2.0 server over stdio.
    """

    def __init__(self, db_path: Optional[str | Path] = None):
        self.config = load_config()
        self.privacy_gate = PrivacyGatekeeper(
            config_path=self.config.privacy.config_path,
            enabled=self.config.privacy.enabled,
        )
        env_db = os.environ.get("MEMVISION_DB_PATH")
        if env_db:
            resolved_db = Path(env_db).resolve()
        elif db_path is not None:
            p = Path(db_path)
            resolved_db = p if p.is_absolute() else _project_root / p
        else:
            configured_db = Path(self.config.storage.database_path)
            resolved_db = configured_db if configured_db.is_absolute() else _project_root / configured_db
        self.storage = MemoryStorage(resolved_db, self.config.storage.enable_fts)
        self.screenshots_dir = Path(self.config.storage.screenshots_dir)
        if not self.screenshots_dir.is_absolute():
            self.screenshots_dir = _project_root / self.screenshots_dir

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Returns the schemas of the tools exposed to AI agents."""
        return [
            {
                "name": "search_desktop_memory",
                "description": "Searches the user's desktop memory for keywords across OCR text, window titles, URLs, and active applications. Supports optional time bounding (since/until) and app filtering for rapid retrieval.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search term, application name, domain, or keyword to look for in memory.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of memory records to return (default: 5).",
                            "default": 5,
                        },
                        "since": {
                            "type": "string",
                            "description": "Optional ISO 8601 timestamp to retrieve memories recorded on or after this time.",
                        },
                        "until": {
                            "type": "string",
                            "description": "Optional ISO 8601 timestamp to retrieve memories recorded on or before this time.",
                        },
                        "app_name": {
                            "type": "string",
                            "description": "Optional application process name filter (e.g., 'code.exe', 'chrome.exe').",
                        },
                        "file_path": {
                            "type": "string",
                            "description": "Optional file path or filename filter (e.g. 'README.md', 'c:/projects/app/main.py').",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "get_recent_memory",
                "description": "Retrieves the most recent desktop screen captures, showing what the user was actively working on, their open tabs, and window titles.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Number of recent captures to return (default: 5).",
                            "default": 5,
                        },
                    },
                },
            },
            {
                "name": "get_capture_details",
                "description": "Retrieves the full OCR text, exact browser URL, and screenshot file path for a specific capture ID.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "capture_id": {
                            "type": "integer",
                            "description": "The ID of the capture record.",
                        },
                    },
                    "required": ["capture_id"],
                },
            },
            {
                "name": "get_memory_statistics",
                "description": "Returns statistics about the desktop memory database (total captures, database size, time range).",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "get_activity_sessions",
                "description": "Retrieves clustered focus sessions / episodes (e.g. coding session in VS Code for 45 mins, browsing documentation for 15 mins) with start/end timestamps, duration, and frame counts.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Number of recent activity sessions to return (default: 10).",
                            "default": 10,
                        },
                    },
                },
            },
            {
                "name": "get_capture_windows",
                "description": "Retrieves visible top-level windows for a specific capture ID in top-to-bottom Z-order, with their application names, window titles, rectangles, visible fractions, and text snippets.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "capture_id": {
                            "type": "integer",
                            "description": "The ID of the capture record.",
                        },
                    },
                    "required": ["capture_id"],
                },
            },
            {
                "name": "get_window_crop",
                "description": "Retrieves an on-demand high-resolution image crop of a specific window from a capture. Applies privacy redaction/blur and returns MCP image content.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "capture_id": {
                            "type": "integer",
                            "description": "The ID of the capture record.",
                        },
                        "window_id": {
                            "type": "integer",
                            "description": "The ID of the window record (obtained from search_desktop_memory or get_capture_windows).",
                        },
                        "max_px": {
                            "type": "integer",
                            "description": "Maximum dimension (width or height) for the returned crop (default: 1024).",
                            "default": 1024,
                        },
                    },
                    "required": ["capture_id", "window_id"],
                },
            },
        ]

    def handle_tool_call(self, name: str, args: Dict[str, Any]) -> Any:
        """Executes the requested tool and returns the result."""
        if name == "search_desktop_memory":
            query = args.get("query", "")
            limit = int(args.get("limit", 5))
            since = args.get("since")
            until = args.get("until")
            app_name = args.get("app_name")
            file_path = args.get("file_path")
            records = self.storage.search(query, limit=limit, since=since, until=until, app_name=app_name, file_path=file_path)
            results = []
            for r in records:
                windows = self.storage.get_windows_by_capture_id(r.id)
                matching_window = None
                if windows:
                    if query:
                        q_lower = query.lower()
                        for w in windows:
                            if (q_lower in (w.ocr_text or "").lower() or
                                q_lower in (w.title or "").lower() or
                                q_lower in (w.app_name or "").lower() or
                                q_lower in (w.url or "").lower()):
                                matching_window = w
                                break
                    if not matching_window:
                        for w in windows:
                            if w.is_foreground:
                                matching_window = w
                                break
                    if not matching_window:
                        matching_window = windows[0]

                if matching_window:
                    snippet = make_snippet(matching_window.ocr_text or r.ocr_text, query)
                    win_info = {
                        "window_id": matching_window.id,
                        "hwnd": matching_window.hwnd,
                        "app": matching_window.app_name,
                        "app_name": matching_window.app_name,
                        "title": matching_window.title,
                        "url": matching_window.url,
                        "is_foreground": bool(matching_window.is_foreground),
                        "visible_fraction": matching_window.visible_fraction,
                        "rect": {
                            "x": matching_window.rect_x,
                            "y": matching_window.rect_y,
                            "w": matching_window.rect_w,
                            "h": matching_window.rect_h,
                        },
                        "snippet": snippet,
                    }
                    results.append({
                        "id": r.id,
                        "timestamp": r.timestamp,
                        "app_name": matching_window.app_name,
                        "window_title": matching_window.title,
                        "file_path": r.file_path,
                        "url": matching_window.url,
                        "is_foreground": bool(matching_window.is_foreground),
                        "visible_fraction": matching_window.visible_fraction,
                        "window_id": matching_window.id,
                        "ocr_snippet": snippet,
                        "screenshot_path": r.screenshot_path,
                        "crop_path": matching_window.crop_path,
                        "window": win_info,
                        "matching_window": win_info,
                        "all_windows": [
                            {
                                "window_id": w.id,
                                "app_name": w.app_name,
                                "title": w.title,
                                "is_foreground": bool(w.is_foreground),
                                "visible_fraction": w.visible_fraction,
                            }
                            for w in windows
                        ],
                    })
                else:
                    snippet = make_snippet(r.ocr_text, query)
                    results.append({
                        "id": r.id,
                        "timestamp": r.timestamp,
                        "app_name": r.app_name,
                        "window_title": r.window_title,
                        "file_path": r.file_path,
                        "url": r.url,
                        "is_foreground": True,
                        "visible_fraction": 1.0,
                        "window_id": None,
                        "ocr_snippet": snippet,
                        "screenshot_path": r.screenshot_path,
                        "crop_path": None,
                        "matching_window": None,
                        "all_windows": None,
                    })
            return results

        elif name == "get_recent_memory":
            limit = int(args.get("limit", 5))
            records = self.storage.get_recent(limit=limit)
            return [
                {
                    "id": r.id,
                    "timestamp": r.timestamp,
                    "app_name": r.app_name,
                    "window_title": r.window_title,
                    "file_path": r.file_path,
                    "url": r.url,
                    "ocr_snippet": make_snippet(r.ocr_text, max_chars=300),
                    "screenshot_path": r.screenshot_path,
                }
                for r in records
            ]

        elif name == "get_capture_details":
            capture_id = int(args.get("capture_id", 0))
            record = self.storage.get_by_id(capture_id)
            if not record:
                return {"error": f"Capture #{capture_id} not found"}
            windows = self.storage.get_windows_by_capture_id(capture_id)
            return {
                "id": record.id,
                "timestamp": record.timestamp,
                "app_name": record.app_name,
                "window_title": record.window_title,
                "file_path": record.file_path,
                "url": record.url,
                "full_ocr_text": record.ocr_text,
                "screenshot_path": record.screenshot_path,
                "metadata": record.metadata,
                "windows": [
                    {
                        "window_id": w.id,
                        "app_name": w.app_name,
                        "title": w.title,
                        "url": w.url,
                        "is_foreground": bool(w.is_foreground),
                        "visible_fraction": w.visible_fraction,
                        "crop_path": w.crop_path,
                        "rect": {"x": w.rect_x, "y": w.rect_y, "w": w.rect_w, "h": w.rect_h},
                    }
                    for w in windows
                ] if windows else None,
            }

        elif name == "get_capture_windows":
            capture_id = int(args.get("capture_id", 0))
            windows = self.storage.get_windows_by_capture_id(capture_id)
            if not windows:
                cap = self.storage.get_by_id(capture_id)
                if not cap:
                    return {"error": f"Capture #{capture_id} not found"}
                return [
                    {
                        "window_id": None,
                        "app_name": cap.app_name,
                        "title": cap.window_title,
                        "url": cap.url,
                        "z_index": 0,
                        "is_foreground": True,
                        "visible_fraction": 1.0,
                        "rect": {"x": 0, "y": 0, "w": cap.width, "h": cap.height},
                        "ocr_snippet": make_snippet(cap.ocr_text, max_chars=300),
                        "has_crop": bool(cap.screenshot_path),
                    }
                ]
            return [
                {
                    "window_id": w.id,
                    "hwnd": w.hwnd,
                    "app_name": w.app_name,
                    "pid": w.pid,
                    "title": w.title,
                    "url": w.url,
                    "z_index": w.z_index,
                    "is_foreground": bool(w.is_foreground),
                    "visible_fraction": w.visible_fraction,
                    "monitor": w.monitor,
                    "rect": {"x": w.rect_x, "y": w.rect_y, "w": w.rect_w, "h": w.rect_h},
                    "ocr_snippet": make_snippet(w.ocr_text, max_chars=300),
                    "has_crop": bool(w.crop_path),
                }
                for w in windows
            ]

        elif name == "get_window_crop":
            capture_id = int(args.get("capture_id", 0))
            window_id = int(args.get("window_id", 0))
            max_px = int(args.get("max_px", 1024))

            win = self.storage.get_window_by_id(window_id)
            cap = self.storage.get_by_id(capture_id)
            if not cap and not win:
                return {"error": f"Capture #{capture_id} / Window #{window_id} not found"}

            crop_img = None
            if win and win.crop_path and Path(win.crop_path).is_file():
                try:
                    crop_img = Image.open(win.crop_path).convert("RGB")
                except Exception as e:
                    logger.debug("Failed to open crop_path %s: %s", win.crop_path, e)

            if crop_img is None and win and win.crop_path:
                alt = self.screenshots_dir / Path(win.crop_path).name
                if alt.is_file():
                    try:
                        crop_img = Image.open(alt).convert("RGB")
                    except Exception:
                        pass

            if crop_img is None and cap and cap.screenshot_path and Path(cap.screenshot_path).is_file():
                try:
                    full_screenshot = Image.open(cap.screenshot_path).convert("RGB")
                    if win and win.rect_w > 0 and win.rect_h > 0:
                        origin_x = 0
                        origin_y = 0
                        meta = cap.metadata or {}
                        if isinstance(meta, dict) and "virtual_origin" in meta:
                            origin_x, origin_y = meta["virtual_origin"]
                        rx1 = max(0, min(full_screenshot.width, win.rect_x - origin_x))
                        ry1 = max(0, min(full_screenshot.height, win.rect_y - origin_y))
                        rx2 = max(0, min(full_screenshot.width, win.rect_x + win.rect_w - origin_x))
                        ry2 = max(0, min(full_screenshot.height, win.rect_y + win.rect_h - origin_y))
                        if rx2 > rx1 and ry2 > ry1:
                            crop_img = full_screenshot.crop((rx1, ry1, rx2, ry2))
                    if crop_img is None:
                        crop_img = full_screenshot
                except Exception as e:
                    logger.error("Failed to crop from full screenshot: %s", e)

            if crop_img is None:
                return {"error": f"Image crop not available for capture #{capture_id}, window #{window_id}"}

            app_name = win.app_name if win else (cap.app_name if cap else "unknown")
            title = win.title if win else (cap.window_title if cap else "")
            url = win.url if win else (cap.url if cap else None)
            decision = self.privacy_gate.evaluate(app_name=app_name, window_title=title, url=url)
            is_redacted = decision.action in ("drop", "redact")
            if is_redacted:
                crop_img = crop_img.filter(ImageFilter.GaussianBlur(radius=25))

            if max(crop_img.width, crop_img.height) > max_px:
                crop_img.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)

            buf = io.BytesIO()
            crop_img.save(buf, format="JPEG", quality=75)
            b64_data = base64.b64encode(buf.getvalue()).decode("utf-8")

            logger.info(
                "Served get_window_crop: capture=%d, window=%d, app='%s', size=%dx%d, bytes=%d, redacted=%s",
                capture_id,
                window_id,
                app_name,
                crop_img.width,
                crop_img.height,
                len(buf.getvalue()),
                is_redacted,
            )

            return [
                {
                    "type": "image",
                    "data": b64_data,
                    "mimeType": "image/jpeg",
                }
            ]

        elif name == "get_memory_statistics":
            return self.storage.get_stats()

        elif name == "get_activity_sessions":
            limit = int(args.get("limit", 10))
            episodes = self.storage.get_episodes(limit=limit)
            return [
                {
                    "id": ep.id,
                    "app_name": ep.app_name,
                    "title": ep.title,
                    "url": ep.url,
                    "start_time": ep.start_time,
                    "end_time": ep.end_time,
                    "duration_seconds": ep.duration_seconds,
                    "duration_minutes": round(ep.duration_seconds / 60, 1),
                    "capture_count": ep.capture_count,
                    "summary_keywords": ep.summary_keywords,
                }
                for ep in episodes
            ]

        else:
            raise ValueError(f"Unknown tool: {name}")

    def run_stdio(self) -> None:
        """Runs the JSON-RPC 2.0 loop reading from stdin and writing to stdout."""
        logger.info("mem-vision-mcp MCP Server started listening on stdio.")

        # Ensure UTF-8 on Windows stdio
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8")
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                request = json.loads(line)
            except Exception as e:
                logger.error("JSON parse error: %s", e)
                continue

            msg_id = request.get("id")
            method = request.get("method")
            params = request.get("params", {})

            # Respond according to MCP protocol specification
            if method == "initialize":
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "serverInfo": {
                            "name": "mem-vision-mcp",
                            "version": "0.1.0",
                        },
                        "capabilities": {
                            "tools": {},
                        },
                    },
                }
                self._send_response(response)

            elif method == "notifications/initialized":
                # Notification from client, no response required
                pass

            elif method == "tools/list":
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "tools": self.get_tool_definitions(),
                    },
                }
                self._send_response(response)

            elif method == "tools/call":
                tool_name = params.get("name")
                tool_args = params.get("arguments", {})
                try:
                    tool_result = self.handle_tool_call(tool_name, tool_args)
                    if isinstance(tool_result, list) and len(tool_result) > 0 and isinstance(tool_result[0], dict) and "type" in tool_result[0]:
                        content_blocks = tool_result
                    elif isinstance(tool_result, dict) and "content" in tool_result and isinstance(tool_result["content"], list):
                        content_blocks = tool_result["content"]
                    else:
                        content_blocks = [
                            {
                                "type": "text",
                                "text": json.dumps(tool_result, indent=2) if not isinstance(tool_result, str) else tool_result,
                            }
                        ]
                    response = {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "content": content_blocks
                        },
                    }
                except Exception as err:
                    response = {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "isError": True,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"Error executing tool {tool_name}: {err}",
                                }
                            ]
                        },
                    }
                self._send_response(response)

            elif method == "ping":
                self._send_response({"jsonrpc": "2.0", "id": msg_id, "result": {}})

            else:
                # Method not found
                if msg_id is not None:
                    response = {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {
                            "code": -32601,
                            "message": f"Method not found: {method}",
                        },
                    }
                    self._send_response(response)

    def _send_response(self, response: Dict[str, Any]) -> None:
        """Sends a JSON-RPC message line to stdout."""
        msg = json.dumps(response)
        sys.stdout.write(msg + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    db_arg = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else None
    server = MCPServer(db_path=db_arg)
    server.run_stdio()
