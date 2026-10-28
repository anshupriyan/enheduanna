# Meta Model API & Provider Integration Notes

This document summarizes the technical findings for integrating the Meta Model API and local/OpenAI-compatible proxies (e.g. Omniroute) into the Enheduanna core integration service.

---

## 1. Core Endpoints & Protocols

Meta Model API (`https://api.meta.ai/v1`) supports three wire protocols against the same model catalog:

| Protocol | Endpoint | Best Suited For | Tool-Calling Schema |
| :--- | :--- | :--- | :--- |
| **Responses API** | `POST /v1/responses` | Multi-turn reasoning agents | Top-level function definitions (`tools: [{ type: "function", name, description, parameters }]`) |
| **Chat Completions** | `POST /v1/chat/completions` | Omniroute / OpenAI-compatible proxies | Nested function objects (`tools: [{ type: "function", function: { name, description, parameters } }]`) |
| **Messages API** | `POST /v1/messages` | Anthropic SDK / Claude Code clients | Anthropic content blocks |

### Implementation Decision
To support both **Meta Model API (Muse Spark 1.3 / Wonder 1.0)** directly and **Omniroute (`http://localhost:20128/v1`)** seamlessly:
* The core provider layer implements a dual-mode adapter:
  1. `meta-responses`: Native `/v1/responses` for Meta API.
  2. `openai-compatible`: Standard `/v1/chat/completions` (compatible with Omniroute, OpenAI SDK, and local gateways).
* Both wire schemas translate cleanly to and from the internal MCP tool definitions.

---

## 2. Authentication & Headers

* **Header**: `Authorization: Bearer <API_KEY>`
* **Environment Variable**: `META_API_KEY` (or `MODEL_API_KEY`, `OMNIROUTE_API_KEY`)
* **Security**: The API key is stored strictly on the server in `.env` / `enheduanna.config.json` and in memory during runtime. It is never logged, exposed via `/health`, or returned to the browser client.

---

## 3. Tool Calling Format & Execution

### MCP Schema to Model Tool Schema
MCP tools from both `cli-bridge` and `memvison` declare JSON Schema `inputSchema`.
The adapter maps:
```typescript
{
  type: "function",
  name: tool.name, // e.g., "search_desktop_memory" or "cli_read_file"
  description: tool.description,
  parameters: tool.inputSchema
}
```

### Parallel Execution
When the model returns multiple tool call invocations in a single turn, the orchestrator dispatches them concurrently via `Promise.allSettled`.

### Result Truncation & Fetching
* OCR texts or large directory listings exceeding `maxToolResultLength` (default 4,000 characters) are truncated.
* A unique ID (`buf_<hash>`) is generated and stored in a short-lived LRU buffer.
* A virtual internal tool `get_full_result(result_id: string)` is registered so the model can inspect full payloads if needed without overwhelming the context window.

---

## 4. Streaming Format

* **Transport**: Server-Sent Events (`text/event-stream`).
* **Client Events Emitted by Enheduanna**:
  * `delta`: Incremental text tokens for real-time typing effect.
  * `tool_call`: Emitted when a tool call begins, with arguments preview.
  * `tool_result`: Emitted when a tool call completes (with status, duration, and output preview).
  * `done`: Signals the conclusion of the turn with full updated message history.
  * `error`: Emits user-friendly error messages if upstream fails.

---

## 5. Reasoning Preservation

* In the **Responses API**, multi-turn continuity is maintained by passing `previous_response_id: <response_id>` along with the new tool results, preserving encrypted reasoning state across turns.
* In **Chat Completions** / Omniroute, conversation history is preserved by appending the assistant's `tool_calls` message followed by matching `tool` result messages with corresponding `tool_call_id`.

---

## 6. Tools Catalog

### `memvison` (Screen Memory Layer)
1. `search_desktop_memory`: Query OCR text, window titles, URLs, file paths.
2. `get_recent_memory`: Recent desktop captures with active apps.
3. `get_capture_details`: Full OCR text and screenshot path for a specific capture ID.
4. `get_activity_sessions`: Clustered task sessions and focus episodes.
5. `get_memory_statistics`: Total captures, DB size, time range.

### `cli-bridge` (Workspace Execution Layer)
1. Filesystem: `read_file`, `write_file`, `edit_file`, `list_directory`, `search_files`, `grep_content`.
2. Execution: `execute_command` (Dev Mode gated), `toggle_dev_mode`.
3. Policy: `request_path_access`, `request_command_access`.
4. Journal: `log_journal_entry`, `get_recent_journal_entries`.
