"""
Tests for Model Context Protocol (MCP) server.
Validates initialize, tools/list, and tools/call over JSON-RPC.
"""

import json
import subprocess
import sys
from pathlib import Path


def test_mcp_server_protocol():
    python_exe = sys.executable
    server_script = str(Path(__file__).resolve().parent.parent / "src" / "memvision" / "mcp_server.py")

    proc = subprocess.Popen(
        [python_exe, server_script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )

    try:
        # 1. Test initialize
        init_req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        proc.stdin.write(init_req + "\n")
        proc.stdin.flush()

        resp_line = proc.stdout.readline()
        init_resp = json.loads(resp_line)
        assert init_resp.get("id") == 1
        assert "serverInfo" in init_resp.get("result", {})
        assert init_resp["result"]["serverInfo"]["name"] == "mem-vision-mcp"

        # 2. Test tools/list
        tools_req = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        proc.stdin.write(tools_req + "\n")
        proc.stdin.flush()

        tools_resp = json.loads(proc.stdout.readline())
        assert tools_resp.get("id") == 2
        tools = tools_resp.get("result", {}).get("tools", [])
        tool_names = [t["name"] for t in tools]
        assert "search_desktop_memory" in tool_names
        assert "get_recent_memory" in tool_names
        assert "get_capture_details" in tool_names
        assert "get_memory_statistics" in tool_names
        assert "get_activity_sessions" in tool_names

        # 3. Test tools/call (get_memory_statistics)
        call_req = json.dumps({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "get_memory_statistics",
                "arguments": {},
            },
        })
        proc.stdin.write(call_req + "\n")
        proc.stdin.flush()

        call_resp = json.loads(proc.stdout.readline())
        assert call_resp.get("id") == 3
        content = call_resp.get("result", {}).get("content", [])
        assert len(content) > 0
        stats = json.loads(content[0]["text"])
        assert "total_captures" in stats

    finally:
        proc.terminate()
        proc.wait(timeout=3)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    test_mcp_server_protocol()
    print("[PASS] MCP Server JSON-RPC test passed successfully!")
