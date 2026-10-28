# Enheduanna — Next Session Plan & Master Action Roadmap

**Target Sprint:** Post-Core Architecture, Bug Hardening & Next-Gen Capabilities  
**Cross-References:**
- Achievements Log: [`docs/TODAYS_ACHIEVEMENTS.md`](TODAYS_ACHIEVEMENTS.md)
- Self-Audit & Judge Readiness: [`HACKATHON_STATUS_AUDIT.md`](../HACKATHON_STATUS_AUDIT.md)
- Meta API Specs & Adapters: [`docs/meta-api-notes.md`](meta-api-notes.md)
- Master Architecture & Mythos: [`README.md`](../README.md)
- System Prompt & Personas: [`app/core/prompts/system_prompt.txt`](../app/core/prompts/system_prompt.txt)
- Active Configuration: [`enheduanna.config.json`](../enheduanna.config.json)

---

## 1. Mid-Loop Stuck & HTTP 400 Error Diagnostics & Fix

During stress-testing on deep repository queries (`check my projects on github tell me my best project...`), two specific mid-loop failures were captured in screenshots:

### A. HTTP 400 Invalid Request Parameter on Multi-Step Visual Calls
- **Symptom:** At Step 6 of 8 (following `get_screenshot` calls), Meta's API returned:
  ```json
  [Error: API returned HTTP 400: {"error":{"code":null,"message":"The request contains invalid parameters. Check the request body for any errors or inconsistencies.","param":null,"type":"invalid_request_error"}}]
  ```
- **Root Cause Analysis (`app/core/src/agent/orchestrator.ts:504-530`):**
  1. **Illegal Message Sequencing:** In Meta's API (and the standard OpenAI/Responses schema), an assistant message containing `tool_calls` **must be followed exclusively by `role: "tool"` messages** matching each `tool_call_id`.
  2. **Mid-Stream System & User Messages:** The current code injects a `role: "user"` message with `image_url` and a `role: "system"` message (`[VERIFIED TIMELINE EVIDENCE]`) directly into the middle of the tool-response sequence. Meta's validator rejects `system` messages placed anywhere other than index 0.
  3. **Multi-Megabyte Base64 Payloads:** Multiple full-resolution screenshots embedded as data URIs within conversation history blow past request payload size limits.
- **Action for Tomorrow:**
  - Enforce strict message sequence: All `tool` messages must complete before any follow-up guidance.
  - Move verified evidence text directly into the tool result content or the initial system prompt rather than appending mid-stream `system` messages.
  - Cap visual images to a single high-resolution crop per turn, thumbnailing or downsizing to 1024px max before base64 transmission.

### B. Consecutive `execute_command` Stalling Loop
- **Symptom:** On the `continue` turn, the orchestrator fired 8 consecutive `execute_command` calls in a row without breaking into synthesis.
- **Action for Tomorrow:**
  - Enforce an Operator Action Limit: After 3 consecutive shell executions without textual progress, force a synthesis step with Wonder 1.0 to narrate progress to the user.

---

## 2. Screenshot Storage Optimization: WebP vs. JPEG

- **Current State:** `memvision` captures and stores screenshots as JPEG (`.jpg`/`.jpeg`) at quality 75. Across 3,500+ captures, this consumes ~50MB disk space and generates heavy base64 strings during MCP tool execution.
- **Goal:** Migrate `memvision`'s internal storage and crop generation pipeline to **WebP (`.webp`)**:
  - WebP achieves **25%–35% smaller file sizes** at identical visual fidelity.
  - Reduces SQLite blob / filesystem footprint significantly.
  - Decreases base64 string size across stdio MCP pipes, reducing JSON serialization latency and IPC overhead.
- **Action for Tomorrow:**
  - Update `memvision/capture.py` to save captures as `.webp`.
  - Update `mcp_server.py` (`get_screenshot`, `get_window_crop`) to encode images as `image/webp`.
  - Update `app/core/src/mcp/manager.ts` and `styles.css` to accept and render `image/webp`.

---

## 3. Resolving Enheduanna's Own Self-Critiques (from Audit)

Referenced in detail in [`HACKATHON_STATUS_AUDIT.md`](../HACKATHON_STATUS_AUDIT.md):

### A. Deterministic API Key Handshake (Eliminate Step 1 401s)
- Ensure boot-time resolution between `.env`, `enheduanna.config.json`, and client-supplied keys is 100% deterministic so a live demo never flashes an initial unauthorized box.

### B. Eliminate Loop Chattiness (`get_full_result` Cache Over-Fetching)
- Optimize the truncation threshold in `app/core/src/mcp/buffer.ts` from 4,000 to 6,000 characters for memory tools so Spark 1.3 doesn't waste intermediate steps retrieving buffered full results.

### C. Test Execution Verification on Camera
- Execute both `pytest` (in `memvison/`) and `node --test` (in `app/core/`) visibly and take a clean screenshot for judges.

---

## 4. CLI-Bridge Polishing for Enheduanna

- **Interactive Code Diffs in Chat:** Surface unified side-by-side diff widgets before applying modifications from `replace_in_file` or `write_file`.
- **Streaming Terminal Output:** Stream stdout/stderr line-by-line over SSE into a live terminal drawer for long commands (`npm build`, `cargo test`).
- **Dynamic Path Whitelisting:** Add an "Always Allow for This Session" checkbox to the approval card.

---

## 5. SAM (Segment Anything Model) Integration

- **Pixel-Perfect Spatial Privacy Redaction:** Run MobileSAM / FastSAM on sensitive window coordinates to mask *only* specific password inputs or private messages, keeping the rest of the window visible.
- **Precise UI Element Bounding:** Expose `segment_screen_element` tool for fine-grained button and widget visual inspection.
- **Lightweight ONNX Runtime:** Run MobileSAM on DirectML/CUDA with `<120ms` latency and zero LLM VRAM interference.

---

## 6. On-Screen Real-Time Support & "Clear Time" Engine

- **"Clear Time" vs. Idle Classification:** Integrate Windows `GetLastInputInfo` into `memvision/capture.py` to tag captures with idle seconds and report verified clear focus time vs. AFK intervals.
- **Adaptive Capture Loop:** Perceptual hash diffing (`imagehash.phash`) to throttle capture rate to 10–15s when screen is static and accelerate to 1s during rapid typing and tab switches.
- **Desktop Companion HUD:** Floating companion pill showing active session, clear time, and pause toggle.

---

## 7. Master Action Checklist for Tomorrow

1. [ ] **Fix HTTP 400 Bug:** Fix message role sequencing in `orchestrator.ts` (stop mid-stream `system` messages and base64 bloat).
2. [ ] **Operator Guard:** Limit consecutive `execute_command` tool calls to prevent stalling loops.
3. [ ] **WebP Optimization:** Switch `memvision` capture and crop format from JPEG to WebP for 30% storage savings.
4. [ ] **Buffer Threshold:** Tune `toolResultBuffer` threshold to reduce `get_full_result` chatty round trips.
5. [ ] **CLI-Bridge:** Build streaming terminal output drawer for long commands.
6. [ ] **SAM Integration:** Benchmark MobileSAM ONNX model against sample captures.
7. [ ] **Clear Time:** Add `GetLastInputInfo` idle measurement to `memvision`.
