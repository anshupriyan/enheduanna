# 🌐 Meta Model API & Meta Hackathon Official Technical Reference

> **Primary Documentation Source**: [https://dev.meta.ai/docs/overview](https://dev.meta.ai/docs/overview)  
> **Platform & API Key Dashboard**: [https://dev.meta.ai/platform](https://dev.meta.ai/platform)  
> **Base Inference Endpoint**: `https://api.meta.ai/v1`  
> **Authentication Header**: `Authorization: Bearer $MODEL_API_KEY`  
> **Date Compiled**: October 2026

---

## 📑 Direct Navigation & Quick Links

If you need deeper live context on any specific topic, click directly on the URLs below:

| Documentation Surface | Direct URL | Description |
| :--- | :--- | :--- |
| **API Overview** | [dev.meta.ai/docs/overview](https://dev.meta.ai/docs/overview) | High-level overview of Meta Model API, Muse models, and Muse Code. |
| **Quickstart** | [dev.meta.ai/docs/quickstart](https://dev.meta.ai/docs/quickstart) | First API call with cURL, Python (OpenAI SDK), and TypeScript. |
| **Authentication** | [dev.meta.ai/docs/authentication](https://dev.meta.ai/docs/authentication) | API key creation, environment variables (`MODEL_API_KEY`), key rotation. |
| **Models Directory** | [dev.meta.ai/docs/models](https://dev.meta.ai/docs/models) | Model matrix: Wonder, Spark, Image, Voice Transcribe, SAM 3.1, Spark Open, Glimmer. |
| **Protocols Comparison** | [dev.meta.ai/docs/protocols](https://dev.meta.ai/docs/protocols) | Compare Responses API, Chat Completions, and Messages API wire formats. |
| **Pricing & Rate Limits** | [dev.meta.ai/docs/pricing-rate-limits](https://dev.meta.ai/docs/pricing-rate-limits) | Pay-as-you-go rates, Standard vs Contributor modes, team rate limits. |
| **Tool Calling** | [dev.meta.ai/docs/tool-calling](https://dev.meta.ai/docs/tool-calling) | Function definitions, parallel tool calls, multi-turn reasoning preservation. |
| **Search Grounding** | [dev.meta.ai/docs/search-grounding](https://dev.meta.ai/docs/search-grounding) | Built-in `web_search` tool for real-time live web facts. |
| **Tool Search** | [dev.meta.ai/docs/tool-search](https://dev.meta.ai/docs/tool-search) | Dynamic semantic search across large catalogs of agent tools. |
| **Image Generation** | [dev.meta.ai/docs/image-generation](https://dev.meta.ai/docs/image-generation) | Generate, edit, and iteratively refine images with `muse-image-1.0`. |
| **Speech-to-Text** | [dev.meta.ai/docs/speech-to-text](https://dev.meta.ai/docs/speech-to-text) | Realtime WebSocket & batch audio transcription with `muse-voice-transcribe-1.0`. |
| **Media Segmentation** | [dev.meta.ai/docs/media-segmentation](https://dev.meta.ai/docs/media-segmentation) | Text-prompted object masks and video bounding box tracking with `sam-3.1`. |
| **File Handling** | [dev.meta.ai/docs/file-handling](https://dev.meta.ai/docs/file-handling) | Upload and manage images, PDFs, audio, and video via `/v1/files`. |
| **Reasoning Controls** | [dev.meta.ai/docs/reasoning](https://dev.meta.ai/docs/reasoning) | Reasoning effort settings (`minimal`, `low`, `medium`, `high`, `max`). |
| **Coding Agents Guide** | [dev.meta.ai/docs/coding-agents](https://dev.meta.ai/docs/coding-agents) | Wiring Meta Model API into OpenCode, Goose, Roo, Claude Code, Cursor. |
| **Muse Code CLI** | [dev.meta.ai/docs/muse-code](https://dev.meta.ai/docs/muse-code) | Meta's native terminal agent CLI (`muse`), workflows, CI/CD integration. |
| **Muse Spark Open** | [dev.meta.ai/docs/muse-spark-open](https://dev.meta.ai/docs/muse-spark-open) | Open-weight 816B MoE (42B active) weights (BF16, NVFP4) for self-hosting. |
| **Muse Glimmer** | [dev.meta.ai/docs/muse-glimmer](https://dev.meta.ai/docs/muse-glimmer) | Lightweight edge multimodal model (Apache 2.0) for local hardware. |
| **API Reference (OpenAPI)**| [dev.meta.ai/docs/api-reference](https://dev.meta.ai/docs/api-reference) | Full schemas, parameters, response objects, error status codes. |
| **Help Center** | [dev.meta.ai/help](https://dev.meta.ai/help) | Account, billing, token allowances, and enterprise support. |

---

## 🤖 The Meta Model Matrix

Meta Model API hosts 5 production model lines, plus 2 open-weight releases:

### 1. Hosted Frontier & Reasoning Models

| Model Name | Model ID | Context Window | Output Limit | Primary Use Cases |
| :--- | :--- | :--- | :--- | :--- |
| **Muse Wonder 1.0** | `muse-wonder-1.0` | **1,048,576 tokens** (1M) | 131,072 tokens | Long-horizon autonomous agentic tasks, multi-file code refactors, sub-agent delegation, computer use. Supports reasoning levels from `minimal` to `max`. |
| **Muse Spark 1.3** | `muse-spark-1.3`<br>`muse-spark-1.3-contributor` | **1,048,576 tokens** (1M) | 131,072 tokens | Default flagship agent model. Multi-step tool loops, fast coding assistant, high-throughput agent loops. Replays encrypted reasoning across turns. |
| **Muse Spark 1.2** | `muse-spark-1.2`<br>`muse-spark-1.2-contributor` | **1,048,576 tokens** (1M) | 131,072 tokens | Previous stable generation. Includes full native audio understanding. |
| **Muse Spark 1.1** | `muse-spark-1.1` | **1,048,576 tokens** (1M) | 131,072 tokens | Original generation (Standard mode only). |

> [!NOTE]
> **Standard Mode vs. Contributor Mode**:
> - **Standard Mode** (`muse-spark-1.3`): Standard token pricing; prompts, code, and completions are **never** used to train Meta models.
> - **Contributor Mode** (`muse-spark-1.3-contributor`): Heavily discounted token pricing in exchange for permitting Meta to train future models on inputs/outputs. Switchable via model ID.

---

### 2. Specialized Multimodal Models

| Model Name | Model ID | Protocol / Endpoint | Modalities & Capabilities |
| :--- | :--- | :--- | :--- |
| **Muse Image 1.0** | `muse-image-1.0` | Responses API (`/v1/responses`) or<br>`/v1/images/generations`<br>`/v1/images/edits` | Text-to-image generation and multi-turn conversational image editing. Agentic: searches web for visual references and runs layout code before rendering. |
| **Muse Voice Transcribe 1.0** | `muse-voice-transcribe-1.0` | WebSocket: `wss://api.meta.ai/v1/asr/realtime`<br>REST: `POST /v1/asr/transcribe` | Real-time streaming and file-based speech-to-text. Includes speaker diarization, voice activity detection (VAD), contextual biasing, and 25 languages with code-switching. |
| **Segment Anything 3.1 (SAM 3.1)** | `sam-3.1` | Responses API (`POST /v1/responses`) | Point/box/text-prompted object segmentation across images and video. Returns pixel masks and coordinates; tracks objects across video frames. |

---

### 3. Open-Weight Model Releases

| Model | Parameters | Checkpoint Formats | Deployment Runtimes | License |
| :--- | :--- | :--- | :--- | :--- |
| **Muse Spark Open** | 816B Mixture-of-Experts (42B active) | BF16, NVFP4 | SGLang, vLLM, TensorRT-LLM, llama.cpp | Open Weights |
| **Muse Glimmer** | Distilled edge multimodal | Quantized INT4/INT8, FP16 | vLLM, SGLang, llama.cpp, ExecuTorch (mobile/on-device) | **Apache 2.0** |

---

## ⚡ API Wire Protocols: Choosing the Right Format

Meta Model API supports **three distinct wire protocols** against the same underlying backend (`https://api.meta.ai/v1`), using the same `$MODEL_API_KEY` and charging the same token pricing:

```
                            ┌─────────────────────────────────────────┐
                            │        https://api.meta.ai/v1           │
                            └────────────────────┬────────────────────┘
                                                 │
                   ┌─────────────────────────────┼─────────────────────────────┐
                   ▼                             ▼                             ▼
       ┌───────────────────────┐     ┌───────────────────────┐     ┌───────────────────────┐
       │     Responses API     │     │ Chat Completions API  │     │     Messages API      │
       │   POST /v1/responses  │     │ POST /v1/chat/complet │     │   POST /v1/messages   │
       └───────────────────────┘     └───────────────────────┘     └───────────────────────┘
       • Recommended for Agents      • Classic OpenAI drop-in      • Anthropic wire-format
       • Encrypted reasoning replay  • Function tool calling       • Claude Code compatibility
       • Native previous_response_id • Simple single-turn apps     • Stateless client history
       • Built-in search grounding   • OpenAI SDK compatibility    • Anthropic SDK drop-in
```

### Protocol Comparison Matrix

| Feature | Responses API (`/v1/responses`) | Chat Completions (`/v1/chat/completions`) | Messages API (`/v1/messages`) |
| :--- | :--- | :--- | :--- |
| **Best For** | Multi-turn AI agents & coding assistants | Fast drop-in for OpenAI-compatible code | Claude Code & Anthropic-oriented tools |
| **Reasoning Continuity** | ✅ Full encrypted token replay | ❌ Stateless across turns | ⚠️ Client-side history replay |
| **Tool Calling Format** | Top-level function schema | Nested under `function` object | Anthropic tool blocks |
| **Search Grounding** | ✅ Supported (`web_search`) | ❌ Not available | ✅ Supported |
| **Tool Search** | ✅ Supported (`tool_search`) | ❌ Not available | ✅ Supported |
| **Target SDK** | `@ai-sdk/openai`, OpenAI SDK | OpenAI SDK, LangChain, LlamaIndex | Anthropic SDK (`@anthropic-ai/sdk`) |

---

## 🔑 Authentication & Environment Setup

Get an API key from the [Meta Model API Dashboard](https://dev.meta.ai/platform).

### Environment Variables

```powershell
# Windows PowerShell
$env:MODEL_API_KEY = "your-actual-api-key-here"

# If using libraries that expect OPENAI_API_KEY:
$env:OPENAI_API_KEY = $env:MODEL_API_KEY
$env:OPENAI_BASE_URL = "https://api.meta.ai/v1"
```

```bash
# macOS / Linux
export MODEL_API_KEY="your-actual-api-key-here"
export OPENAI_API_KEY="$MODEL_API_KEY"
export OPENAI_BASE_URL="https://api.meta.ai/v1"
```

---

## 💻 Working Code Examples

### 1. Python — Official OpenAI SDK (Responses API)

```python
import os
from openai import OpenAI

client = OpenAI(
    base_url="https://api.meta.ai/v1",
    api_key=os.environ["MODEL_API_KEY"],
)

response = client.responses.create(
    model="muse-spark-1.3",
    input="Analyze the performance characteristics of SQLite WAL mode vs rollback journal.",
    reasoning={"effort": "high"}
)

print(response.output_text)
```

---

### 2. Python — Direct HTTP (httpx / requests)

```python
import os
import requests

url = "https://api.meta.ai/v1/responses"
headers = {
    "Authorization": f"Bearer {os.environ['MODEL_API_KEY']}",
    "Content-Type": "application/json",
}
payload = {
    "model": "muse-spark-1.3",
    "input": "Write an async Python function that monitors desktop window changes.",
    "reasoning": {"effort": "high"},
}

response = requests.post(url, headers=headers, json=payload)
response.raise_for_status()
data = response.json()

# Extract assistant output text:
for item in data.get("output", []):
    if item.get("type") == "message":
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                print(content.get("text"))
```

---

### 3. cURL — Direct Terminal Test

```bash
curl -X POST "https://api.meta.ai/v1/responses" \
  -H "Authorization: Bearer $MODEL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "muse-spark-1.3",
    "reasoning": { "effort": "high" },
    "input": "Hello Meta Model API!"
  }'
```

---

### 4. Tool Calling Pattern (Responses API)

```json
{
  "model": "muse-spark-1.3",
  "input": "What was I working on in my desktop memory 10 minutes ago?",
  "tools": [
    {
      "type": "function",
      "name": "search_desktop_memory",
      "description": "Searches captured desktop OCR text, window titles, and URLs.",
      "parameters": {
        "type": "object",
        "properties": {
          "query": { "type": "string", "description": "Keywords to search" },
          "limit": { "type": "integer", "default": 5 }
        },
        "required": ["query"],
        "additionalProperties": false
      }
    }
  ]
}
```

---

## 🛠️ Muse Code CLI (Ready-Made Terminal Coding Agent)

Meta provides **Muse Code**, a native terminal coding assistant built on `muse-spark-1.3`:

### Installation

```powershell
# Windows (PowerShell)
irm https://dev.meta.ai/install.ps1 | iex
```

```bash
# macOS / Linux
curl -fsSL https://dev.meta.ai/install.sh | sh
```

### Launching

```bash
# Start Muse Code (prompts for browser sign-in or paste API key on first run)
muse
```

---

## 💰 Pricing & Rate Limits Summary

* **Context Windows**: Full **1,048,576 tokens (1M)** on Wonder and Spark models.
* **No Long-Context Penalty**: Same cost per token regardless of context utilization.
* **Prompt Caching**: Substantial discounts when requests share cached prefixes.
* **Web Search Grounding**: $2.50 per 1,000 live search queries.
* **Rate Limits**: Governed at the **Team** level across all API keys; independent rate-limit quotas per model ID.
