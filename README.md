# Enheduanna 📜

> **The Autonomous Desktop Scribe & Execution Framework for AI**  
> Built for the Meta Global AI Hackathon.

Named after **Enheduanna** (~2300 BCE) — the world's first recorded author in human history who first etched personal thought and experience onto clay cuneiform tablets — this framework provides desktop AI with the two faculties required for true autonomy:

1. **The Scribe (`memvison/`)**: Continuous local perception, high-frequency OCR, temporal scene clustering, text stability gating, and zero-leak privacy redaction.
2. **The Operator (`cli-bridge/`)**: Sandboxed, policy-governed command execution, interactive session approvals, and structured tool interfaces.

---

## 🏛️ System Architecture

Enheduanna coordinates perception and action into a unified autonomous stack via the **Model Context Protocol (MCP)**:

```
                       ┌─────────────────────────────────────┐
                       │        LLM / Desktop Agent          │
                       │   (Meta Llama 3.3 / Claude / etc.)  │
                       └──────────────────┬──────────────────┘
                                          │
                   ┌──────────────────────┴──────────────────────┐
                   │                                             │
                   ▼ (MCP)                                       ▼ (MCP)
        ┌─────────────────────┐                       ┌─────────────────────┐
        │     memvison/       │                       │     cli-bridge/     │
        │  [The Memory Scribe]│                       │   [The CLI Operator]│
        ├─────────────────────┤                       ├─────────────────────┤
        │ • Continuous Capture│                       │ • Sandboxed CLI     │
        │ • Windows OCR/WinRT │                       │ • Policy Guardrails │
        │ • SQLite FTS5 Search│                       │ • Session Approvals │
        │ • Privacy Redaction │                       │ • Audit Logging     │
        │ • Scene Clustering  │                       │ • JIT Path Grants   │
        │ • Video Suppression │                       │ • Dynamic Allowlist │
        │ • Draft Collapsing  │                       │ • Symlink Hardened  │
        └─────────────────────┘                       └─────────────────────┘
```

---

## 📂 Monorepo Components

### 1. [`memvison/`](./memvison) — Perception & Memory Layer
- **Continuous Local Screen Capture & WinRT OCR**: Ultra-low latency desktop activity tracking without cloud dependency.
- **Text Stability Gating**:
  - *Video & Animation Suppression*: Intelligently detects moving pixels with static text (YouTube, Netflix, VLC) and drops redundant frames.
  - *Incremental Draft Collapsing*: Merges continuous typing bursts into a single complete record, deleting obsolete partial drafts.
- **Privacy & Security First**: Zero-leak regex redaction for API keys, tokens, and credentials + spatial blackout masking for multi-window setups.
- **Temporal Episodic Clustering**: Intelligent grouping of desktop actions into coherent activity episodes.
- **Glassmorphic Web Dashboard**: Real-time visual telemetry, query inspector, and privacy controls.
- **MCP Server**: Exposes memory and semantic search tools (`search_desktop_memory`, `get_recent_memory`, `get_activity_sessions`, `get_memory_statistics`).
- **Meta Model API Reference**: Full integration guide with Meta Llama 3.3 and Meta AI inference protocols.

### 2. [`cli-bridge/`](./cli-bridge) — Secure Action Execution Layer
- **Controlled Command Bridge**: Safe execution of terminal commands, development builds, and system tasks.
- **Granular Policy Engine**: Policy-defined access control (`allow`, `ask`, `deny`) preventing destructive actions.
- **Session Approvals**: Interactive and transparent human-in-the-loop approvals for sensitive CLI tools.
- **Hardened Path Security**: Protected against dangling symlink escapes (CWE-59) with strict workspace boundaries.
- **MCP Server**: Exposes structured execution capabilities directly to AI models.

---

## 🚀 Quick Start

### Prerequisites
- **Node.js** v18+ (for `cli-bridge`)
- **Python** 3.10+ (for `memvison`)
- **Windows 10/11** (for hardware-accelerated WinRT OCR capture)

### 1. Setting up `memvison`
```bash
cd memvison
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py ui
```
*Web dashboard launches at `http://127.0.0.1:8765`.*

### 2. Setting up `cli-bridge`
```bash
cd cli-bridge
npm install
npm run build
```

---

## 🔒 Security & Privacy Guarantees
- **100% Local Execution**: Perceptual frames, OCR indexes, and memory stores remain strictly on your local machine.
- **Proactive Secret Redaction**: High-entropy keys (OpenAI, Anthropic, Meta, AWS, GitHub, JWTs) are scrubbed before reaching storage or context windows.
- **Bounded Tool Access**: Commands executed via `cli-bridge` require explicit policy definitions, blocking unauthorized filesystem or network operations.

---

## 📜 License
MIT License. Created for the Meta Global AI Hackathon.