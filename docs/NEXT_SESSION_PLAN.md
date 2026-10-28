# Enheduanna — Next Session Plan & Roadmap

**Target Sprint:** Post-Core Architecture & UX Stabilization  
**Key Focus Areas:** CLI-Bridge Polishing • SAM (Segment Anything Model) Integration • On-Screen Real-Time & "Clear Time" Engine

---

## 1. CLI-Bridge Polishing for Enheduanna

While `cli-bridge` handles secure file operations, search, and guarded command execution, the operator experience can be refined into a best-in-class desktop pair programmer:

### A. In-Chat Interactive Code & File Diffs
- **Problem:** Currently, when the agent proposes file edits or writes, the changes execute immediately (or prompt for blanket allow/deny).
- **Goal:** Surface a GitHub-style side-by-side or inline unified diff widget in the chat before applying modifications.
- **Implementation:**
  - Enhance `replace_in_file` and `write_file` in `cli-bridge` to return a unified diff patch.
  - Render an interactive diff view in `app/dashboard/app.js` with "Accept Diff" / "Reject Diff" buttons.

### B. Streaming Terminal Output for Long Commands
- **Problem:** Commands like `npm build`, `cargo test`, or `python main.py` currently block until completion before returning output.
- **Goal:** Stream stdout/stderr line-by-line over SSE into an embedded terminal drawer in the chat turn.
- **Implementation:**
  - Add `onChunk` streaming callback to `execute_command` in `cli-bridge/src/tools/execute.ts`.
  - Pipe live output chunks via `event: command_output_chunk` directly into a monospace terminal card.

### C. Dynamic Policy & Path Ergonomics
- **Goal:** Allow the user to grant temporary or permanent path whitelisting directly from the chat interface without manually editing `policy.json`.
- **Implementation:**
  - Add "Always Allow for This Session" checkbox to the approval card.
  - Automatically update the runtime policy set in `policy/approver.ts`.

---

## 2. SAM (Segment Anything Model) Integration

Integrating Meta's **Segment Anything Model (SAM / MobileSAM / SAM 2)** into `memvision` unlocks frontier-grade visual spatial intelligence:

### A. Pixel-Perfect Spatial Privacy Redaction
- **Current Limitation:** Privacy redaction currently blurs the entire rectangular bounding box of a sensitive window (e.g. whole browser window when an auth page opens).
- **SAM Solution:**
  - Run fast edge-guided or prompt-guided SAM segmentation on sensitive coordinates.
  - Mask and blur *only* the specific password field, private chat message, or credit card input, leaving the surrounding workspace, IDE, and reference material completely visible and readable to the model.

### B. Precise UI Element Bounding & On-Demand Element Crops
- **Goal:** Enable the agent to identify and crop specific UI elements (buttons, modals, tables, graph widgets) on demand.
- **Implementation:**
  - Add `segment_screen_element(capture_id, point_or_box)` tool to `memvision/mcp_server.py`.
  - Returns cropped element PNG + segment mask for visual verification.
  - Allows Muse models to answer hyper-specific visual questions (*"What is the exact text inside that error popup on the right monitor?"*).

### C. Resource Optimization (MobileSAM / ONNX Runtime)
- Use **MobileSAM** or **FastSAM** running on ONNX Runtime with DirectML/CUDA acceleration:
  - Latency target: `<120ms` per frame segmentation.
  - Zero interference with local LLM GPU VRAM.

---

## 3. On-Screen Real-Time Support & "Clear Time" Engine

Enheduanna must accurately distinguish deep focus from ambient idling, providing a truthful timeline of the user's computer day:

### A. "Clear Time" vs. Idle Classification
- **Definition of Clear Time:** Continuous, verified active engagement with the computer (active keystrokes, mouse moves, foreground window changes, terminal activity) as opposed to leaving a screen on while walking away.
- **Implementation:**
  - Integrate user input idle counters (`GetLastInputInfo` on Windows) into `memvision/capture.py`.
  - Tag each capture record with `idle_seconds: number` and `is_clear_time: boolean`.
  - Update `get_session_summaries` to compute:
    $$\text{Clear Time} = \text{Total Span} - \text{Idle Intervals} (> 3 \text{ mins})$$
  - Model prompt updated: *"When reporting session length, always state both Total Span and verified Clear Time (e.g. '1h 15m session, 58m clear focus time')."*

### B. Adaptive Screen Capture Loop (Low-Overhead Live Sampling)
- **Problem:** Static 2-second capture loops either capture too much duplicate data or miss brief 1-second tab switches.
- **Solution:**
  - Perceptual hash diffing (`imagehash.phash` or structural similarity):
    - If screen is static: throttle capture rate to 10–15s to save CPU and SQLite storage.
    - If active typing or rapid tab switching is detected: accelerate capture rate to 1s.

### C. Desktop Floating HUD / Live Companion
- **Goal:** A minimalist, lightweight status bar or tray companion:
  - Displays current active session name and recorded Clear Time.
  - Single-click toggle to Pause / Resume recording.
  - Floating pill showing active Meta model connection status.

---

## 4. Immediate Next Sprint Checklist

1. [ ] **CLI-Bridge:** Wire unified diff preview into `replace_in_file` and frontend.
2. [ ] **CLI-Bridge:** Implement streaming stdout chunks for `execute_command`.
3. [ ] **SAM Integration:** Benchmark MobileSAM ONNX model against sample desktop captures in `memvison/scripts/`.
4. [ ] **SAM Integration:** Expose `segment_window_element` tool via `memvision/mcp_server.py`.
5. [ ] **Clear Time:** Add Windows `GetLastInputInfo` idle measurement to `memvision/capture.py`.
6. [ ] **Clear Time:** Update session summary clustering to calculate net active focus minutes.
7. [ ] **Dashboard:** Add Clear Time visual badges to session timeline cards.
