"""
Model Context Protocol (MCP) Server for mem-vision-mcp.
Exposes local desktop memory, OCR search, and context retrieval as MCP tools for AI agents
(compatible with Claude Desktop, Cursor, and any MCP client via JSON-RPC over stdio).
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure parent directory is in sys.path when executed directly
_src_dir = str(Path(__file__).resolve().parent.parent)
_project_root = Path(__file__).resolve().parent.parent.parent
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from memvision.config import load_config
from memvision.storage import MemoryStorage

# Configure logger to output only to stderr (stdout must be exclusively JSON-RPC messages)
logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="[MCP] %(message)s")
logger = logging.getLogger("mcp_server")


class MCPServer:
    """
    Standard MCP (Model Context Protocol) JSON-RPC 2.0 server over stdio.
    """

    def __init__(self, db_path: Optional[str | Path] = None):
        self.config = load_config()
        import os
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
            return [
                {
                    "id": r.id,
                    "timestamp": r.timestamp,
                    "app_name": r.app_name,
                    "window_title": r.window_title,
                    "file_path": r.file_path,
                    "url": r.url,
                    "ocr_snippet": r.ocr_text[:300] if r.ocr_text else "",
                    "screenshot_path": r.screenshot_path,
                }
                for r in records
            ]

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
                    "ocr_snippet": r.ocr_text[:300] if r.ocr_text else "",
                    "screenshot_path": r.screenshot_path,
                }
                for r in records
            ]

        elif name == "get_capture_details":
            capture_id = int(args.get("capture_id", 0))
            record = self.storage.get_by_id(capture_id)
            if not record:
                return {"error": f"Capture #{capture_id} not found"}
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
            }

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
                    response = {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(tool_result, indent=2),
                                }
                            ]
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
