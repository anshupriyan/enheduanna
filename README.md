# mem-vision-mcp

> **A 100% open-source, local-first continuous desktop memory layer that captures screen context, extracts window and browser tab URLs, runs on-device OCR, stores structured history in SQLite with FTS5 search, and exposes this memory via a glassmorphic Web Dashboard and Model Context Protocol (MCP) tools for AI agents.**

Built for the **Meta Global AI Developer Hackathon**. 100% open-source with permissive licenses (MIT, BSD, Apache 2.0). Zero closed-source SDKs, zero telemetry, zero mandatory cloud dependencies.  
See [`META_MODEL_API_REFERENCE.md`](file:///c:/meta%20hackathon/memvison/META_MODEL_API_REFERENCE.md) for full Meta Model API, Muse models, and hackathon documentation.

---

## Architecture Overview

`mem-vision-mcp` is designed as a lightweight, zero-cloud desktop background daemon with decoupled subsystems:

```
                  ┌────────────────────────────────────────┐
                  │          Continuous Screen Loop        │
                  └───────────────────┬────────────────────┘
                                      │
                         [Screen Capturer: mss/GDI]
                                      │
                         [Perceptual Change Detector]
                                      │ (Diff > Threshold)
                         ┌────────────┴────────────┐
                         │    Context Extractor    │
                         │  (Active App, Title,    │
                         │   Browser Active URL)   │
                         └────────────┬────────────┘
                                      │
                    ══════════════════▼══════════════════
                    🔒 PRIVACY GATEKEEPER (Priority #1)
                    - Check App against Blocklist
                    - Check URL against Blocklist
                    - Check Window Title against Regex
                    ══════════════════┬══════════════════
                          /                       \
                  [BLOCKED]                       [PASSED]
                     /                               \
        ┌───────────────────────────┐         ┌───────────────────────────────┐
        │  Action: DROP or REDACT   │         │  Local OCR (WinRT / Tesseract)│
        │  - Drop: Discard entirely │         │  - Windows Native WinRT OCR   │
        │  - Redact: Masked stub    │         │  - 0 Network, ~70ms latency   │
        │  - 0 Disk, 0 OCR, 0 Leak  │         │  - Full Native Res in RAM     │
        └───────────────────────────┘         └───────────────┬───────────────┘
                                                              │
                                              ┌───────────────▼───────────────┐
                                              │    Local SQLite + FTS5 Index  │
                                              │  - WAL mode (high-throughput) │
                                              │  - Full-text keyword search   │
                                              │  - Compressed JPEG / WebP     │
                                              │  - ~39 KB storage per capture │
                                              └───────┬───────────────┬───────┘
                                                      │               │
                                   ┌──────────────────▼─┐   ┌─────────▼──────────────────┐
                                   │ 🌐 Web Dashboard   │   │ 🔌 MCP Server (stdio)      │
                                   │ - Dark Glassmorphic│   │ - Claude Desktop & Cursor  │
                                   │ - Live Timeline    │   │ - search_desktop_memory    │
                                   │ - OCR Text Viewer  │   │ - get_recent_memory        │
                                   │ - AI Memory Chat   │   │ - get_capture_details      │
                                   └────────────────────┘   │ - get_memory_statistics    │
                                                            └────────────────────────────┘
```

---

## Key Technical Innovations

1. **Windows Native Hardware-Accelerated OCR**:
   Uses Microsoft's official Windows Runtime (`winrt.windows.media.ocr.OcrEngine`) built directly into Windows 10/11. Captures are OCR'd directly from in-memory BMP byte streams in 70–200ms with zero cloud calls, zero external binaries, and zero internet connection required.
2. **Dual-Resolution Memory Architecture**:
   Maintains 100% native resolution (e.g. 4480×1440) in RAM during OCR for crystal-clear small-font recognition, then downsamples using high-quality Lanczos resampling to 720p / 1280px before saving to disk. Image size drops from ~500 KB to ~39 KB per capture.
3. **Perceptual Difference Hashing (0% Idle CPU)**:
   Computes 64-bit difference hashes (`dhash`) using OpenCV/numpy matrix operations. Static screens, cursor blinks, and minor clock ticks are skipped with 0% CPU consumption.
4. **Context & Active Tab URL Extraction**:
   Uses Windows UI Automation to retrieve the active URL from Chrome, Edge, Brave, and Firefox tab bars, attaching the exact web address to the captured screen frame.
5. **Weighted Relevance Ranking for AI Memory**:
   Conversation questions ("What was that link I saw earlier?") trigger keyword extraction and stop-word filtering across SQLite FTS5 index with boosting for browser URLs (+30) and window titles (+20).

---

## Open-Source License Compliance

Every dependency is strictly permissively licensed (compliant with Meta Hackathon rules):

| Package | Version | License | Role |
| :--- | :--- | :--- | :--- |
| **mss** | `>=10.2.0` | **MIT** | Ultra-fast screen capture via native Windows GDI |
| **Pillow** | `>=10.0.0` | **HPND / Open-Source** | Image scaling, compression, JPEG/WebP serialization |
| **imagehash** | `>=4.3.1` | **BSD-2-Clause** | Difference hashing (`dhash`) & perceptual hashing (`phash`) |
| **numpy** | `>=1.26.0` | **BSD-3-Clause** | Fast matrix operations for hashing |
| **psutil** | `>=5.9.0` | **BSD-3-Clause** | Process name and system context identification |
| **pywin32** | `>=306` | **PSF / BSD** | Windows Win32 API bindings |
| **uiautomation**| `>=2.0.19` | **Apache-2.0** | Windows UI Automation to extract active browser tab URLs |
| **winrt-*** | `>=4.0.0` | **MIT** | Microsoft official WinRT bindings for on-device native OCR |
| **httpx** | `>=0.27.0` | **BSD-3-Clause** | Transport for Meta Model API, OmniRoute, and local LLMs |
| **sqlite3** | Built-in | **Public Domain** | SQLite database with FTS5 full-text indexing |

---

## Quickstart

### 1. Installation

```powershell
# Clone repository
git clone https://github.com/your-repo/mem-vision-mcp.git
cd memvison

# Create virtual environment and install dependencies
uv venv
.\.venv\Scripts\activate
uv pip install -e .
```

### 2. Start Continuous Capture

```powershell
# Run the continuous capture daemon (interval: 2.0s, difference threshold: 6)
python main.py run
```

### 3. Launch Web Dashboard

```powershell
# Launches dark-mode glassmorphic dashboard at http://127.0.0.1:8765
python main.py ui
```

### 4. Chat with Your Memory via CLI

```powershell
# Interactive chat
python main.py chat

# Direct question
python main.py chat "What was that Meta Model API documentation link?"
```

### 5. Full-Text Memory Search

```powershell
python main.py search "Meta Model API"
python main.py search "GitHub pull request" -l 5
```

---

## Model Context Protocol (MCP) Setup

`mem-vision-mcp` implements the standard MCP JSON-RPC 2.0 stdio protocol. External AI assistants (Claude Desktop, Cursor, Windsurf, Zed) can search your desktop memory and retrieve screenshot context natively.

To view your exact configuration paths:
```powershell
python main.py mcp-config
```

### Claude Desktop Integration

Edit `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "memvision": {
      "command": "C:\\meta hackathon\\memvison\\.venv\\Scripts\\python.exe",
      "args": [
        "C:\\meta hackathon\\memvison\\src\\memvision\\mcp_server.py"
      ]
    }
  }
}
```

### Cursor Integration

Create or edit `.cursor/mcp.json` in your workspace:

```json
{
  "mcpServers": {
    "memvision": {
      "command": "C:\\meta hackathon\\memvison\\.venv\\Scripts\\python.exe",
      "args": [
        "C:\\meta hackathon\\memvison\\src\\memvision\\mcp_server.py"
      ]
    }
  }
}
```

### Exposed MCP Tools

1. `search_desktop_memory(query, limit)`: Full-text search across OCR text, window titles, URLs, and applications.
2. `get_recent_memory(limit)`: Retrieves most recent captures with timestamps, active apps, and URLs.
3. `get_capture_details(capture_id)`: Fetches complete OCR text, exact URL, and screenshot file path.
4. `get_memory_statistics()`: Returns total captures, DB size, and capture timestamps.

---

## AI Providers & OmniRoute Configuration

`mem-vision-mcp` supports any OpenAI-compatible provider, Meta Model API, local Ollama, and OmniRoute proxy.

### OmniRoute (Claude / Free-Stack)
If you run an OmniRoute proxy locally:
```powershell
$env:ANTHROPIC_BASE_URL = "http://localhost:20128"
$env:ANTHROPIC_AUTH_TOKEN = "your-token-here"
$env:ANTHROPIC_MODEL = "free-stack"
```

### Meta Model API / OpenAI / OpenRouter
```powershell
$env:OPENAI_API_KEY = "your-api-key"
$env:OPENAI_BASE_URL = "https://api.meta.ai/v1" # or OpenRouter/Groq
```

---

## Privacy Gatekeeper Configuration

Privacy rules are evaluated before OCR and disk persistence. Edit `config/privacy_rules.json`:

```json
{
  "blocked_apps": [
    "1password.exe",
    "keepass.exe",
    "bitwarden.exe",
    "discord.exe"
  ],
  "blocked_urls": [
    "*login*",
    "*bank*",
    "*paypal.com*",
    "*discord.com*"
  ],
  "blocked_titles": [
    ".*password.*",
    ".*private browsing.*",
    ".*incognito.*",
    ".*discord.*"
  ],
  "default_action": "drop"
}
```

Test your privacy rules instantly:
```powershell
python main.py privacy-test --app discord.exe
python main.py privacy-test --url https://discord.com/channels/123
```

---

## Testing

Run the automated test suite:
```powershell
pytest
```
All 10 unit tests pass 100% green:
- `test_privacy.py`: Privacy gatekeeper allowlist/blocklist/redact validation
- `test_change_detector.py`: Perceptual difference hashing & hamming distance
- `test_storage.py`: SQLite WAL mode, FTS5 triggers, and search queries
- `test_ai_chat.py`: Memory retrieval and weighted ranking
- `test_mcp.py`: JSON-RPC protocol compliance (`initialize`, `tools/list`, `tools/call`)
- `test_web_server.py`: REST API endpoints and asset serving

---

## License

MIT License. Free and open source for the community.
