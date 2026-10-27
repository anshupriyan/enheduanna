# Janus ??

> **The Dual-Faced Autonomous Agent Architecture for Desktop AI**  
> Built for the Meta Global AI Hackathon.

Janus is an open-source, privacy-preserving desktop autonomous agent framework that bridges **continuous perceptual memory** with **secure tool execution**. In Roman mythology, *Janus* is the god of transitions, doorways, and dual perspectives—looking simultaneously to the past (memory) and to the future (action).

---

## ??? System Architecture

Janus unifies two modular engines into a cohesive autonomous agent stack via the Model Context Protocol (MCP):

`
                       +-------------------------------------+
                       ¦        LLM / Desktop Agent          ¦
                       ¦   (Meta Llama 3.3 / Claude / etc.)  ¦
                       +-------------------------------------+
                                          ¦
                   +---------------------------------------------+
                   ¦                                             ¦
                   ? (MCP)                                       ? (MCP)
        +---------------------+                       +---------------------+
        ¦     memvison/       ¦                       ¦     cli-bridge/     ¦
        ¦  [Perception & Past]¦                       ¦   [Action & Future] ¦
        +---------------------¦                       +---------------------¦
        ¦ • Continuous Capture¦                       ¦ • Sandboxed CLI     ¦
        ¦ • Windows OCR/WinRT ¦                       ¦ • Policy Guardrails ¦
        ¦ • SQLite FTS5 Search¦                       ¦ • Session Approvals ¦
        ¦ • Privacy Redaction ¦                       ¦ • Audit Logging     ¦
        ¦ • Scene Clustering  ¦                       ¦ • Granular Allowlist¦
        +---------------------+                       +---------------------+
`

---

## ?? Monorepo Components

### 1. [memvison/](./memvison) — Perception & Memory Layer
- **Continuous Local Screen Capture & OCR**: Ultra-low latency desktop activity tracking without cloud dependency.
- **Privacy & Security First**: Zero-leak regex redaction for sensitive API keys, tokens, and credentials + spatial blackout masking for multi-window privacy.
- **Temporal Episodic Clustering**: Intelligent grouping of desktop actions into coherent activity episodes.
- **Glassmorphic Web Dashboard**: Real-time visual telemetry, query inspector, and privacy controls.
- **MCP Server**: Directly exposes memory and semantic search tools (search_memory, get_recent_activity, get_stats) to AI assistants.
- **Meta Model API Reference**: Full integration guide with Meta Llama 3.3 and Meta AI inference protocols.

### 2. [cli-bridge/](./cli-bridge) — Secure Action Execution Layer
- **Controlled Command Bridge**: Safe execution of terminal commands, development builds, and system tasks.
- **Granular Policy Engine**: Policy-defined access control (llow, sk, deny) preventing destructive actions.
- **Session Approvals**: Interactive and transparent human-in-the-loop approvals for sensitive CLI tools.
- **MCP Server**: Exposes structured execution capabilities directly to AI models.

---

## ?? Quick Start

### Prerequisites
- **Node.js** v18+ (for cli-bridge)
- **Python** 3.10+ (for memvison)
- **Windows 10/11** (for hardware-accelerated WinRT OCR capture)

### Setting up memvison
`ash
cd memvison
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py ui
`
*Web dashboard launches at http://127.0.0.1:8765.*

### Setting up cli-bridge
`ash
cd cli-bridge
npm install
npm run build
`

---

## ?? Security & Privacy Guarantees
- **100% Local Execution**: Perceptual frames, OCR indexes, and memory stores remain strictly on your local machine.
- **Proactive Secret Redaction**: High-entropy keys (OpenAI, Anthropic, Meta, AWS, GitHub, JWTs) are scrubbed before reaching storage or context windows.
- **Bounded Tool Access**: Commands executed via cli-bridge require explicit policy definitions, blocking unauthorized filesystem or network operations.

---

## ?? License
MIT License. Created for the Meta Global AI Hackathon.
