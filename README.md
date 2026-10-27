<div align="center">

<img src="assets/enheduanna.gif" width="400" alt="Enheduanna" />

```text
       .____________________________________________________________________.
       |                                                                    |
       |   ______      __              __                                   |
       |  / ____/___  / /_  ___  ____/ /_  ______ _____  ____  ____ _       |
       | / __/ / __ \/ __ \/ _ \/ __  / / / / __ `/ __ \/ __ \/ __ `/       |
       |/ /___/ / / / / / /  __/ /_/ / /_/ / /_/ / / / / / / / /_/ /        |
       |/_____/_/ /_/_/ /_/\___/\__,_/\__,_/\__,_/_/ /_/_/ /_/\__,_/         |
       |                                                                    |
       |     :::  ?? • ?? • ?? • ?? • ??  :::  UR, MESOPOTAMIA • c. 2300 BCE  :::     |
       |                                                                    |
       |   << THE WORLD''S FIRST AUTHOR REBORN AS AN AUTONOMOUS AGENT >>     |
       |====================================================================|
       |  ::  THE MEMORY SCRIBE                ::  THE CLI OPERATOR         |
       |  -------------------------            -------------------------    |
       |  + Continuous WinRT OCR (Native)      + Sandboxed Terminal Bridge  |
       |  + Spatial Window Blackout Curtain    + Granular Policy Guardrails |
       |  + Video & Animation Suppression      + Session Approvals & JIT    |
       |  + Incremental Draft Collapsing       + CWE-59 Symlink Hardening   |
       |  + SQLite FTS5 Episodic Memory        + Standardized MCP Server    |
       |____________________________________________________________________|
```

# ENHEDUANNA

### *Autonomous Desktop Scribe & Tool Execution Framework for AI*

[![Protocol MCP](https://img.shields.io/badge/PROTOCOL-MCP_2.0-6C5CE7?style=for-the-badge&logoColor=white)](https://modelcontextprotocol.io/)
[![Hardware WinRT OCR](https://img.shields.io/badge/ENGINE-WINRT_OCR_100%25-0984E3?style=for-the-badge&logoColor=white)](https://learn.microsoft.com/en-us/uwp/api/windows.media.ocr)
[![Zero-Leak Privacy](https://img.shields.io/badge/SECURITY-ZERO--LEAK_REDACTION-00B894?style=for-the-badge)](./memvison/src/memvision/privacy.py)
[![Architecture Monorepo](https://img.shields.io/badge/STACK-PYTHON_%2B_NODE-2D3436?style=for-the-badge)](./)
[![License MIT](https://img.shields.io/badge/LICENSE-MIT-E17055?style=for-the-badge)](./LICENSE)

---

> *"The creator of the tablet has formed something which has never happened before.*  
> *That which I have said to you in the dead of night, let the singer repeat at high noon."*  
> — **Enheduanna**, High Priestess of Ur (*The Exaltation of Inanna*, c. 2300 BCE)

[**Mythos**](#-mythos--concept) • [**Architecture**](#-dual-faculty-architecture) • [**Faculties**](#-system-faculties) • [**Quick Start**](#-quick-start) • [**Privacy & Stability**](#-privacy--stability-guarantees) • [**Inference Setup**](#-inference--model-integration)

</div>

---

## ? Mythos & Concept

Over **4,300 years ago**, in the ancient Sumerian city of Ur, **Enheduanna** became the **first recorded author in human history**. By pressing her stylus into wet clay and signing her work, she established the very concept of capturing conscious human experience into permanent, structured memory.

Modern desktop AI agents operate with complete amnesia: they cannot perceive what you did minutes ago, and they cannot touch your operating system without risk of uncontrolled destruction.

**Enheduanna** addresses both boundaries through a unified, modular architecture over the **Model Context Protocol (MCP)**:
- **The Scribe (`memvison/`)**: Observes, redacts, extracts, and clusters desktop activity into a searchable, privacy-guarded episodic memory.
- **The Operator (`cli-bridge/`)**: Provides the reasoning model with a policy-bounded, sandboxed execution bridge to run terminal commands, builds, and tools safely.

---

## ? Dual-Faculty Architecture

```
                       +-------------------------------------+
                       ¦        LLM / Desktop Agent          ¦
                       ¦     (Llama / Claude / Custom)       ¦
                       +-------------------------------------+
                                          ¦
                   +---------------------------------------------+
                   ¦                                             ¦
                   ? (Model Context Protocol)                    ? (Model Context Protocol)
        +-------------------------------------+       +-------------------------------------+
        ¦             memvison/               ¦       ¦            cli-bridge/              ¦
        ¦        [THE MEMORY SCRIBE]          ¦       ¦         [THE CLI OPERATOR]          ¦
        +-------------------------------------¦       +-------------------------------------¦
        ¦ + Continuous Native WinRT OCR       ¦       ¦ + Policy-Engine (allow/ask/deny)    ¦
        ¦ + Spatial Blackout Curtains         ¦       ¦ + Sandboxed Shell Execution         ¦
        ¦ + Zero-Leak Regex Secret Scrubbing  ¦       ¦ + Interactive Session Approvals     ¦
        ¦ + Video & Animation Suppression     ¦       ¦ + JIT Ephemeral Path Access Grants  ¦
        ¦ + Incremental Draft Collapsing      ¦       ¦ + CWE-59 Symlink Escape Hardened    ¦
        ¦ + Temporal Episode Clustering       ¦       ¦ + Audit Trail & Journal Logging     ¦
        ¦ + SQLite WAL + FTS5 BM25 Search     ¦       ¦ + JSON-RPC 2.0 stdio MCP Server     ¦
        +-------------------------------------+       +-------------------------------------+
```

---

## ? System Faculties

| Faculty | Directory | Role | Core Innovations |
| :--- | :--- | :--- | :--- |
| **The Scribe** | [`memvison/`](./memvison) | **Perceptual Memory** | • **Spatial Masking:** Opaque blackout curtains over private windows in split-screen mode.<br>• **Zero-Leak Scrubbing:** Automatic regex redaction of API keys, tokens, and credentials.<br>• **Stability Gating:** Drops video playback frames with static webpage text.<br>• **Draft Collapse:** In-place accumulation of document writing (replaces 20 drafts with 1). |
| **The Operator** | [`cli-bridge/`](./cli-bridge) | **Tool Execution** | • **Policy Engine:** Declarative JSON policy blocking destructive system actions.<br>• **Human-in-the-Loop:** Interactive session approval for sensitive CLI commands.<br>• **CWE-59 Hardened:** Defense against symlink breakout attacks.<br>• **Scoped Journals:** Granular per-project development journals and execution logs. |

---

## ? Privacy & Stability Guarantees

> [!NOTE]
> **100% Local-First Operation**: Screenshots, OCR indexes, SQLite databases, and terminal actions **never leave your local machine**. There are no external cloud syncs, no telemetry beacons, and zero external subscriptions required.

### 1. Spatial Window Masking (The "Blackout Curtain")
When working side-by-side in split-screen mode, clicking an allowed app (e.g. VS Code) while a private app (e.g. Discord, 1Password) sits visible would normally photograph confidential chats. Enheduanna uses Win32 window enumeration to paint an opaque matte rectangle over restricted windows **before OCR runs**, ensuring **0 characters** are ever indexed.

### 2. Zero-Leak Real-Time Secret Scrubbing
An inline pre-persistence regex scanner intercepts all standard credentials before storage:
- **API Keys**: OpenAI, Anthropic, OpenRouter, Google AI, AWS, HuggingFace, Slack.
- **Tokens & Secrets**: Bearer authentication tokens, JWTs, private keys (`BEGIN PRIVATE KEY`).
- **Retroactive Sanitizer**: Sweeps historical SQLite databases and FTS5 indexes to purge exposed tokens.

### 3. Video & Animation Suppression
Watching video streams (YouTube, Twitch, Netflix, VLC) normally floods memory with 1,000+ redundant frames per hour. Enheduanna evaluates OCR text stability across consecutive frames. If pixels change but the webpage text remains $\ge 90\%$ identical, **the frame is immediately dropped**—saving disk space and CPU.

### 4. Incremental Draft Collapsing
Typing a document or code normally produces dozens of fragmented snapshots (e.g. Paragraph 1, then Paragraphs 1 & 2). Enheduanna recognizes text expansion within a 60-second window, **updates the record in-place**, and **unlinks obsolete partial screenshots from disk**.

---

## ? Quick Start

### System Requirements
- **Windows 10 / 11** (for hardware-accelerated WinRT OCR)
- **Python 3.10+** (for `memvison`)
- **Node.js v18+** (for `cli-bridge`)

### 1. Launch The Scribe (`memvison`)
```bash
cd memvison
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py ui
```
*Glassmorphic dashboard launches at `http://127.0.0.1:8765`.*

### 2. Build The Operator (`cli-bridge`)
```bash
cd cli-bridge
npm install
npm run build
```

### 3. Register with MCP Clients (Claude Desktop / Cursor)
Add both engines to your configuration file (e.g. `%APPDATA%\Claude\claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "enheduanna-scribe": {
      "command": "<REPO_ROOT>/memvison/.venv/Scripts/python.exe",
      "args": ["<REPO_ROOT>/memvison/src/memvision/mcp_server.py"]
    },
    "enheduanna-operator": {
      "command": "node",
      "args": [
        "<REPO_ROOT>/cli-bridge/build/index.js",
        "--policy",
        "<REPO_ROOT>/cli-bridge/policy.json"
      ]
    }
  }
}
```

---

## ? Inference & Model Integration

Enheduanna operates as a client-agnostic MCP bridge. It natively supports any modern LLM via standard JSON-RPC 2.0 tool definitions:

- **Meta Llama 3.3 (70B Instruct)**: Optimized prompt templates and tool calling schemas.
- **Anthropic Claude (3.5 Sonnet)**: Seamless integration via Claude Desktop MCP.
- **Multi-Provider Fallback**: Built-in support for OpenAI, Groq, OpenRouter, DeepSeek, and local Ollama instances.

For protocol specifications and API wire details, see:
[`memvison/META_MODEL_API_REFERENCE.md`](./memvison/META_MODEL_API_REFERENCE.md)

---

## ? Verification & Test Telemetry

```bash
# Run Scribe stability, privacy & OCR unit tests (10/10 passing in 0.26s)
pytest memvison/tests/test_stability.py memvison/tests/test_privacy.py

# Run Operator security & policy test suite
cd cli-bridge && npm test
```

---

## ? License
Released under the **MIT License**.
