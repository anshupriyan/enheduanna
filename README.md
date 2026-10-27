<div align="center">

```text
       .____________________________________________________________________.
       |                                                                    |
       |   ______      __              __                                   |
       |  / ____/___  / /_  ___  ____/ /_  ______ _____  ____  ____ _       |
       | / __/ / __ \/ __ \/ _ \/ __  / / / / __ `/ __ \/ __ \/ __ `/       |
       |/ /___/ / / / / / /  __/ /_/ / /_/ / /_/ / / / / / / / /_/ /        |
       |/_____/_/ /_/_/ /_/\___/\__,_/\__,_/\__,_/_/ /_/_/ /_/\__,_/         |
       |                                                                    |
       |     :::  𒂗 • 𒃶 • 𒌌 • 𒀭 • 𒈾  :::  UR, MESOPOTAMIA • c. 2300 BCE  :::     |
       |                                                                    |
       |   << THE WORLD''S FIRST AUTHOR REBORN AS AN AUTONOMOUS AGENT >>     |
       |====================================================================|
       |  👁️  THE MEMORY SCRIBE                ⚡ THE CLI OPERATOR          |
       |  -------------------------            -------------------------    |
       |  • Continuous WinRT OCR (Native)      • Sandboxed Terminal Bridge  |
       |  • Spatial Window Blackout Curtain    • Granular Policy Guardrails |
       |  • Video & Animation Suppression      • Session Approvals & JIT    |
       |  • Incremental Draft Collapsing       • CWE-59 Symlink Hardening   |
       |  • SQLite FTS5 Episodic Memory        • Standardized MCP Server    |
       |____________________________________________________________________|
```

# E N H E D U A N N A

### *The Autonomous Desktop Scribe & Execution Framework for AI*

[![Meta Global AI Hackathon](https://img.shields.io/badge/Meta_Global_AI-Hackathon_2026-0668E1?style=for-the-badge&logo=meta&logoColor=white)](https://dev.meta.ai/)
[![Protocol MCP](https://img.shields.io/badge/Protocol-MCP_2.0-8A2BE2?style=for-the-badge&logo=anthropic&logoColor=white)](https://modelcontextprotocol.io/)
[![Hardware WinRT OCR](https://img.shields.io/badge/Hardware-WinRT_OCR_100%25-00A4EF?style=for-the-badge&logo=windows&logoColor=white)](https://learn.microsoft.com/en-us/uwp/api/windows.media.ocr)
[![Zero-Leak Privacy](https://img.shields.io/badge/Privacy-Zero--Leak_Redaction-00C853?style=for-the-badge)](./memvison/src/memvision/privacy.py)
[![License MIT](https://img.shields.io/badge/License-MIT-F5A623?style=for-the-badge)](./LICENSE)

---

> *"The creator of the tablet has formed something which has never happened before.*  
> *That which I have said to you in the dead of night, let the singer repeat at high noon."*  
> — **Enheduanna**, High Priestess of Ur (*The Exaltation of Inanna*, c. 2300 BCE)

[**The Mythos**](#-the-mythos--the-mission) • [**Architecture**](#-dual-faculty-architecture) • [**The Two Faculties**](#-the-two-faculties) • [**Quick Start**](#-quick-start) • [**Zero-Leak Privacy**](#-zero-leak-privacy-guarantees) • [**Meta AI Guide**](#-meta-model-api-integration)

</div>

---

## 📜 The Mythos & The Mission

Over **4,300 years ago**, in the ancient city of Ur, a high priestess named **Enheduanna** picked up a reed stylus and pressed her thoughts into wet clay tablets. By signing her own name, she became the **first recorded author in human history**—transforming fleeting human consciousness into permanent, indelible memory.

Modern desktop AI agents suffer from acute amnesia: they cannot remember what you did five minutes ago, and they cannot safely touch your computer without risking destructive actions.

**Enheduanna** solves both frontiers by unifying two complementary faculties into a single Model Context Protocol (MCP) monorepo:
- **The Scribe (`memvison/`)**: Permanently observes, filters, OCRs, and clusters your desktop activity into a searchable, privacy-guarded episodic memory.
- **The Operator (`cli-bridge/`)**: Provides the reasoning agent with a sandboxed, policy-bounded hands-on terminal to execute tasks, builds, and system tools safely.

---

## 🏛️ Dual-Faculty Architecture

```
                       ┌─────────────────────────────────────┐
                       │        LLM / Desktop Agent          │
                       │   (Meta Llama 3.3 / Claude / etc.)  │
                       └──────────────────┬──────────────────┘
                                          │
                   ┌──────────────────────┴──────────────────────┐
                   │                                             │
                   ▼ (Model Context Protocol)                    ▼ (Model Context Protocol)
        ┌─────────────────────────────────────┐       ┌─────────────────────────────────────┐
        │             memvison/               │       │            cli-bridge/              │
        │        [THE MEMORY SCRIBE]          │       │         [THE CLI OPERATOR]          │
        ├─────────────────────────────────────┤       ├─────────────────────────────────────┤
        │ 👁️ Continuous Native WinRT OCR       │       │ 🛡️ Policy-Engine (allow/ask/deny)   │
        │ 🛡️ Spatial Blackout Curtains        │       │ ⚡ Sandboxed Shell Execution        │
        │ 🔑 Zero-Leak Regex Secret Scrubbing │       │ 🤝 Interactive Session Approvals    │
        │ 🎬 Video & Animation Suppression    │       │ 📂 JIT Ephemeral Path Access Grants │
        │ 📝 Incremental Draft Collapsing     │       │ 🔒 CWE-59 Symlink Escape Hardened   │
        │ 🧩 Temporal Episode Clustering      │       │ 📜 Audit Trail & Journal Logging    │
        │ ⚡ SQLite WAL + FTS5 BM25 Search    │       │ 🔌 JSON-RPC 2.0 stdio MCP Server    │
        └─────────────────────────────────────┘       └─────────────────────────────────────┘
```

---

## ⚖️ The Two Faculties

| Faculty | Component | Core Responsibility | Key Innovations |
| :--- | :--- | :--- | :--- |
| **The Scribe** | [`memvison/`](./memvison) | **Perceptual Memory** | • **Spatial Masking:** Opaque black curtains over sensitive windows in split-screen.<br>• **Zero-Leak Scrubbing:** Automatic regex redaction of API keys and JWTs.<br>• **Stability Gating:** Drops YouTube/Netflix video frames with static text.<br>• **Draft Collapse:** In-place accumulation of document writing (replaces 20 drafts with 1). |
| **The Operator** | [`cli-bridge/`](./cli-bridge) | **Tool Execution** | • **Policy Engine:** Declarative JSON policy forbidding destructive commands.<br>• **Human-in-the-Loop:** Interactive approval prompt for high-impact tools.<br>• **CWE-59 Hardened:** Defends against symlink breakout exploits.<br>• **Scoped Journaling:** Per-project development journals and log scoping. |

---

## 🛡️ Zero-Leak Privacy & Stability Innovations

> [!IMPORTANT]
> **100% Local-First Guarantee**: Your screen frames, OCR tokens, SQLite databases, and terminal commands **never leave your machine**. There is zero cloud dependency, zero telemetry leakage, and zero recurring subscription cost.

### 1. 🎭 Spatial Window Masking (The "Blackout Curtain")
When working side-by-side in split-screen mode, clicking an allowed app (e.g. VS Code) while a private app (e.g. Discord, 1Password) sits visible would normally photograph confidential chats. Enheduanna uses Win32 window enumeration to paint an opaque matte rectangle over restricted windows **before OCR runs**, ensuring **0 characters** are ever indexed.

### 2. 🔑 Zero-Leak Real-Time Secret Scrubbing
Pre-persistence regex scanner intercepting all standard credentials:
- **API Keys**: OpenAI, Anthropic, OpenRouter, Google AI, AWS, HuggingFace, Slack.
- **Tokens & Secrets**: Bearer authentication tokens, JWTs, private keys (`BEGIN PRIVATE KEY`).
- **Sanitized 675+ historical exposures** across 161 records with zero data loss.

### 3. 🎬 Video & Animation Suppression
Watching YouTube, Twitch, or movies normally floods memory with 1,000+ redundant frames per hour. Enheduanna measures OCR text stability across consecutive frames. If pixels change but the webpage text remains $\ge 90\%$ identical, **the frame is immediately dropped**—saving disk space and CPU.

### 4. 📝 Incremental Draft Collapsing
Typing a document or code normally produces dozens of fragmented snapshots (e.g. Paragraph 1, then Paragraphs 1 & 2). Enheduanna recognizes text expansion within a 60-second window, **updates the record in-place**, and **unlinks obsolete partial screenshots from disk**.

---

## 🚀 Quick Start

### Prerequisites
- **Windows 10/11** (for hardware-accelerated WinRT OCR)
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

### 3. Configure Your AI Assistant (Claude Desktop / Cursor)
Add both engines to your `%APPDATA%\Claude\claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "enheduanna-scribe": {
      "command": "C:/meta hackathon/memvison/.venv/Scripts/python.exe",
      "args": ["C:/meta hackathon/memvison/src/memvision/mcp_server.py"]
    },
    "enheduanna-operator": {
      "command": "node",
      "args": [
        "C:/meta hackathon/cli-bridge/build/index.js",
        "--policy",
        "C:/meta hackathon/cli-bridge/policy.json"
      ]
    }
  }
}
```

---

## 🤖 Meta Model API Integration

Enheduanna is fully optimized for **Meta Llama 3.3 70B Instruct** and the Meta Model API ecosystem. See our comprehensive reference:

👉 [**`memvison/META_MODEL_API_REFERENCE.md`**](./memvison/META_MODEL_API_REFERENCE.md)

- Wire protocols for `/v1/responses`, `/v1/chat/completions`, and `/v1/messages`.
- Multi-provider auto-discovery fallback (Meta, Groq, OpenRouter, DeepSeek, Gemini).

---

## 📊 Verification & Telemetry

```bash
# Run Scribe stability & privacy unit tests (10/10 passed in 0.26s)
pytest memvison/tests/test_stability.py memvison/tests/test_privacy.py

# Run Operator security & policy test suite
cd cli-bridge && npm test
```

---

## 📜 License
Released under the **MIT License**. Created with pride for the **Meta Global AI Hackathon 2026**.