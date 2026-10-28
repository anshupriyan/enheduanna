// Enheduanna Dashboard Client Logic

(function () {
  let activeSessionId = "";
  let traceSource = null;
  let isGenerating = false;

  // DOM Elements
  const messagesStream = document.getElementById("messages-stream");
  const chatWelcome = document.getElementById("chat-welcome");
  const chatForm = document.getElementById("chat-form");
  const userInput = document.getElementById("user-input");
  const sendBtn = document.getElementById("send-btn");
  const sessionsList = document.getElementById("sessions-list");
  const newChatBtn = document.getElementById("new-chat-btn");
  const tracePanel = document.getElementById("trace-panel");
  const traceEvents = document.getElementById("trace-events");
  const toggleTraceBtn = document.getElementById("toggle-trace-btn");
  const clearTraceBtn = document.getElementById("clear-trace-btn");

  // Status & Toggle Elements
  const quickModelSelect = document.getElementById("quick-model-select");
  const quickReasoningSelect = document.getElementById("quick-reasoning-select");
  const memvisionPill = document.getElementById("memvision-pill");
  const clibridgePill = document.getElementById("clibridge-pill");
  const captureToggleBtn = document.getElementById("capture-toggle-btn");
  const captureStatusText = document.getElementById("capture-status-text");
  const mcpToolsCount = document.getElementById("mcp-tools-count");
  const activeProviderLabel = document.getElementById("active-provider-label");

  // Modals
  const settingsModal = document.getElementById("settings-modal");
  const settingsBtn = document.getElementById("settings-btn");
  const closeSettingsBtn = document.getElementById("close-settings-btn");
  const saveSettingsBtn = document.getElementById("save-settings-btn");

  // Settings inputs
  const settingProvider = document.getElementById("setting-provider");
  const settingBaseUrl = document.getElementById("setting-base-url");
  const settingModelSelect = document.getElementById("setting-model-select");
  const customModelGroup = document.getElementById("custom-model-group");
  const settingModelName = document.getElementById("setting-model-name");
  const settingReasoningEffort = document.getElementById("setting-reasoning-effort");
  const settingApiKey = document.getElementById("setting-api-key");

  // HTTP Helper
  async function apiFetch(endpoint, options = {}) {
    const headers = {
      ...(options.headers || {}),
      "Content-Type": "application/json",
    };

    return fetch(endpoint, { ...options, headers });
  }

  // 3. Bootstrap Services
  async function bootstrap() {
    await loadHealth();
    await loadSessions();
    await loadCaptureStatus();
    connectTraceStream();

    // Periodic health check
    setInterval(loadHealth, 10000);
    setInterval(loadCaptureStatus, 6000);
  }

  // 4. Health & Status
  async function loadHealth() {
    try {
      const res = await apiFetch("/health");
      if (!res.ok) return;
      const data = await res.json();

      const savedModel = localStorage.getItem("enheduanna_model");
      if (savedModel && quickModelSelect) {
        quickModelSelect.value = savedModel;
      } else if (quickModelSelect) {
        quickModelSelect.value = data.modelConfig.modelName;
      }

      const savedReasoning = localStorage.getItem("enheduanna_reasoning_effort");
      if (savedReasoning && quickReasoningSelect) {
        quickReasoningSelect.value = savedReasoning;
      }

      activeProviderLabel.textContent = `${data.modelConfig.provider.toUpperCase()} (${quickModelSelect?.value || data.modelConfig.modelName})`;

      updatePill(memvisionPill, data.mcp.servers.memvision?.connected);
      updatePill(clibridgePill, data.mcp.servers["cli-bridge"]?.connected);

      mcpToolsCount.textContent = `${data.mcp.totalTools} Tools Active`;
    } catch {}
  }

  function updatePill(el, isConnected) {
    if (isConnected) {
      el.classList.remove("disconnected");
      el.querySelector(".dot").style.backgroundColor = "var(--accent-green)";
    } else {
      el.classList.add("disconnected");
      el.querySelector(".dot").style.backgroundColor = "var(--accent-red)";
    }
  }

  // 5. Screen Capture Loop Toggle
  async function loadCaptureStatus() {
    try {
      const res = await apiFetch("/api/capture/status");
      if (!res.ok) return;
      const data = await res.json();
      renderCaptureUI(data.running);
    } catch {}
  }

  function renderCaptureUI(isRunning) {
    if (isRunning) {
      captureToggleBtn.classList.remove("stopped");
      captureStatusText.textContent = "Recording (2s)";
      captureToggleBtn.title = "Screen capture loop is ACTIVE. Click to Pause.";
    } else {
      captureToggleBtn.classList.add("stopped");
      captureStatusText.textContent = "Capture Paused";
      captureToggleBtn.title = "Screen capture is PAUSED. Click to Start recording.";
    }
  }

  captureToggleBtn.addEventListener("click", async () => {
    try {
      const res = await apiFetch("/api/capture/toggle", {
        method: "POST",
        body: JSON.stringify({}),
      });
      const data = await res.json();
      renderCaptureUI(data.running);
    } catch (err) {
      console.error("Failed to toggle capture:", err);
    }
  });

  // Live Trace SSE Stream
  function connectTraceStream() {
    if (traceSource) traceSource.close();

    traceSource = new EventSource("/trace");

    traceSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        renderTraceCard(data);
      } catch {}
    };

    traceSource.onerror = () => {
      // Reconnect handled automatically by browser
    };
  }

  function renderTraceCard(evt) {
    const card = document.createElement("div");
    card.className = `trace-card ${evt.type}`;

    const time = evt.timestamp ? evt.timestamp.substring(11, 19) : "";
    const latency = evt.latencyMs ? `${evt.latencyMs}ms` : "";

    let detailsHtml = "";
    if (evt.type === "tool_group" && evt.data?.tools) {
      detailsHtml = `
        <div class="trace-group-breakdown" style="margin-top:6px; font-size:10px; font-family:var(--font-mono); color:var(--text-secondary); display:flex; flex-direction:column; gap:2px;">
          ${evt.data.tools.map((t) => `<div>• ${escapeHtml(t.name)}: ${t.durationMs}ms ${t.isRepeated ? "(cached)" : ""} ${t.isError ? "(error)" : ""}</div>`).join("")}
        </div>
      `;
    }

    card.innerHTML = `
      <div class="trace-top">
        <span class="trace-badge">${evt.source || "system"}</span>
        <span>${time} ${latency ? `• ${latency}` : ""}</span>
      </div>
      <div class="trace-summary">${escapeHtml(evt.title)}</div>
      ${detailsHtml}
    `;

    traceEvents.appendChild(card);
    traceEvents.scrollTop = traceEvents.scrollHeight;
  }

  clearTraceBtn.addEventListener("click", () => {
    traceEvents.innerHTML = "";
  });

  toggleTraceBtn.addEventListener("click", () => {
    tracePanel.classList.toggle("collapsed");
  });

  // 7. Sessions Management
  async function loadSessions() {
    try {
      const res = await apiFetch("/api/sessions");
      if (!res.ok) return;
      const data = await res.json();

      sessionsList.innerHTML = "";
      if (data.sessions.length === 0) {
        await createNewSession();
        return;
      }

      data.sessions.forEach((s, idx) => {
        const item = document.createElement("div");
        item.className = `session-item ${s.id === activeSessionId || (!activeSessionId && idx === 0) ? "active" : ""}`;
        item.dataset.id = s.id;
        item.innerHTML = `
          <span class="session-item-title">${escapeHtml(s.title || "Untitled")}</span>
        `;
        item.addEventListener("click", () => selectSession(s.id));
        sessionsList.appendChild(item);
      });

      if (!activeSessionId && data.sessions.length > 0) {
        selectSession(data.sessions[0].id);
      }
    } catch {}
  }

  async function createNewSession() {
    try {
      const res = await apiFetch("/api/sessions", {
        method: "POST",
        body: JSON.stringify({ title: "New Conversation" }),
      });
      const newSession = await res.json();
      await loadSessions();
      selectSession(newSession.id);
    } catch {}
  }

  newChatBtn.addEventListener("click", createNewSession);

  async function selectSession(sessionId) {
    activeSessionId = sessionId;
    document.querySelectorAll(".session-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.id === sessionId);
    });

    try {
      const res = await apiFetch(`/api/sessions/${sessionId}`);
      if (!res.ok) return;
      const session = await res.json();
      renderSessionMessages(session.messages || []);
    } catch {}
  }

  function renderMarkdown(mdText) {
    if (!mdText) return "";
    try {
      if (typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
        return DOMPurify.sanitize(marked.parse(mdText));
      }
    } catch (e) {
      console.warn("Markdown render error:", e);
    }
    return escapeHtml(mdText);
  }

  function formatToolResult(raw) {
    if (raw === null || raw === undefined) return "No output";
    let val = raw;

    // Unpack nested JSON strings up to depth 3
    for (let depth = 0; depth < 3; depth++) {
      if (Array.isArray(val) && val.length > 0 && val[0]?.type === "text" && typeof val[0].text === "string") {
        try {
          val = JSON.parse(val[0].text);
          continue;
        } catch {
          val = val[0].text;
          break;
        }
      }
      if (typeof val === "string") {
        const trimmed = val.trim();
        if ((trimmed.startsWith("{") && trimmed.endsWith("}")) || (trimmed.startsWith("[") && trimmed.endsWith("]"))) {
          try {
            val = JSON.parse(trimmed);
            continue;
          } catch {}
        }
      }
      break;
    }

    if (typeof val === "object" && val !== null) {
      return JSON.stringify(val, null, 2);
    }
    return String(val);
  }

  function renderSessionMessages(messages) {
    messagesStream.innerHTML = "";
    const visibleMessages = messages.filter((m) => m.role !== "system");

    if (visibleMessages.length === 0) {
      messagesStream.appendChild(chatWelcome);
      chatWelcome.style.display = "block";
      return;
    }

    chatWelcome.style.display = "none";
    let currentTurnContent = null;

    for (const msg of visibleMessages) {
      if (msg.role === "user") {
        currentTurnContent = null;
        appendUserMessage(msg.content);
      } else if (msg.role === "assistant") {
        if (!currentTurnContent) {
          currentTurnContent = createAssistantRow();
        }

        if (msg.reasoning_content && msg.reasoning_content.trim()) {
          const thinkEl = document.createElement("details");
          thinkEl.className = "thinking-drawer";
          thinkEl.innerHTML = `
            <summary class="thinking-drawer-summary">
              <div class="thinking-left">
                <span class="thinking-label">Thinking</span>
              </div>
              <svg class="thinking-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
            </summary>
            <div class="thinking-drawer-body">${escapeHtml(msg.reasoning_content)}</div>
          `;
          currentTurnContent.appendChild(thinkEl);
        }

        if (msg.tool_calls && msg.tool_calls.length > 0) {
          const groupCard = document.createElement("div");
          groupCard.className = "tool-group-card";
          for (const tc of msg.tool_calls) {
            const chip = createToolChip(tc.id, tc.function.name, tc.function.arguments);
            groupCard.appendChild(chip);
          }
          currentTurnContent.appendChild(groupCard);
        } else if (msg.content && msg.content.trim()) {
          const bubble = document.createElement("div");
          bubble.className = "message-bubble";
          bubble.innerHTML = renderMarkdown(msg.content);
          currentTurnContent.appendChild(bubble);
          collapseEvidence(currentTurnContent);
        }
      } else if (msg.role === "tool") {
        appendInlineToolResult(msg.tool_call_id, msg.name, msg.content);
      }
    }
    messagesStream.scrollTop = messagesStream.scrollHeight;
  }

  // 8. Chat Rendering
  function appendUserMessage(text) {
    chatWelcome.style.display = "none";
    const row = document.createElement("div");
    row.className = "message-row user";
    row.innerHTML = `
      <div class="message-header">You</div>
      <div class="message-bubble">${escapeHtml(text)}</div>
    `;
    messagesStream.appendChild(row);
    messagesStream.scrollTop = messagesStream.scrollHeight;
  }

  function createAssistantRow() {
    chatWelcome.style.display = "none";
    const row = document.createElement("div");
    row.className = "message-row assistant";
    row.innerHTML = `
      <div class="message-header">Enheduanna</div>
      <div class="turn-content"></div>
    `;
    messagesStream.appendChild(row);
    messagesStream.scrollTop = messagesStream.scrollHeight;
    return row.querySelector(".turn-content");
  }

  function createToolChip(id, name, argsStr) {
    const chip = document.createElement("div");
    chip.className = "tool-chip"; // collapsed by default!
    chip.id = `tool-chip-${id}`;

    let parsedArgs = argsStr;
    try {
      if (typeof argsStr === "string") {
        parsedArgs = JSON.stringify(JSON.parse(argsStr), null, 2);
      } else {
        parsedArgs = JSON.stringify(argsStr, null, 2);
      }
    } catch {}

    chip.innerHTML = `
      <div class="tool-chip-header" title="Click to view tool parameters and raw output">
        <span class="tool-chip-name">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
          ${escapeHtml(name)}
        </span>
        <div class="tool-chip-right">
          <span class="tool-chip-status" id="chip-status-${id}">Executing...</span>
          <svg class="tool-chip-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
        </div>
      </div>
      <div class="tool-chip-body" id="chip-body-${id}">
        <div class="tool-section-title">Arguments</div>
        <pre class="tool-json-box">${escapeHtml(parsedArgs)}</pre>
        <div class="tool-section-title" id="result-title-${id}" style="display:none;">Result</div>
        <pre class="tool-json-box" id="result-box-${id}" style="display:none;"></pre>
      </div>
    `;

    chip.querySelector(".tool-chip-header").addEventListener("click", () => {
      chip.classList.toggle("expanded");
    });

    return chip;
  }

  function appendInlineToolResult(callId, name, resultText, meta = {}) {
    const statusEl = document.getElementById(`chip-status-${callId}`);
    const resultTitleEl = document.getElementById(`result-title-${callId}`);
    const resultBoxEl = document.getElementById(`result-box-${callId}`);

    if (statusEl) {
      if (meta.isError) {
        statusEl.textContent = "Error";
        statusEl.className = "tool-chip-status error";
      } else if (meta.isRepeated) {
        statusEl.textContent = "Cached (Repeat Blocked)";
        statusEl.className = "tool-chip-status";
      } else {
        const timeStr = meta.durationMs ? `${meta.durationMs}ms • ` : "";
        statusEl.textContent = `${timeStr}Done`;
        statusEl.className = "tool-chip-status done";
      }
    }

    if (resultTitleEl && resultBoxEl) {
      resultTitleEl.style.display = "block";
      resultBoxEl.style.display = "block";
      resultBoxEl.textContent = formatToolResult(resultText);

      if (meta.hasImage && meta.imageUrl) {
        let existingImg = document.getElementById(`tool-img-${callId}`);
        if (!existingImg) {
          const imgWrap = document.createElement("div");
          imgWrap.className = "tool-image-container";
          imgWrap.id = `tool-img-${callId}`;
          imgWrap.innerHTML = `
            <div class="tool-section-title">Visual Capture Inspection</div>
            <a href="${meta.imageUrl}" target="_blank" rel="noopener noreferrer" title="Click to view full image in new tab">
              <img src="${meta.imageUrl}" class="tool-result-image" alt="Screenshot capture" />
            </a>
          `;
          resultBoxEl.parentNode.insertBefore(imgWrap, resultBoxEl);
        }
      }
    }
  }

  function collapseEvidence(turnContent) {
    const toolGroups = turnContent.querySelectorAll(".tool-group-card, .step-indicator-badge, .step-cap-warning");
    if (toolGroups.length === 0) return;

    let existingDrawer = turnContent.querySelector(".evidence-drawer");
    if (existingDrawer) return;

    const drawer = document.createElement("details");
    drawer.className = "evidence-drawer";

    const totalToolChips = turnContent.querySelectorAll(".tool-chip").length;
    drawer.innerHTML = `
      <summary class="evidence-drawer-summary" title="Click to expand tool execution details and raw evidence">
        <svg class="evidence-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
        <span>Evidence (${totalToolChips} tool call${totalToolChips === 1 ? "" : "s"})</span>
      </summary>
      <div class="evidence-drawer-body"></div>
    `;

    const drawerBody = drawer.querySelector(".evidence-drawer-body");
    toolGroups.forEach((el) => {
      drawerBody.appendChild(el);
    });

    const textBubble = turnContent.querySelector(".message-bubble");
    if (textBubble) {
      turnContent.insertBefore(drawer, textBubble);
    } else {
      turnContent.appendChild(drawer);
    }
  }

  function createApprovalCard(data) {
    const card = document.createElement("div");
    card.className = "approval-card";
    card.id = `approval-${data.id}`;

    const argsJson = data.args && Object.keys(data.args).length > 0
      ? JSON.stringify(data.args, null, 2)
      : "";

    card.innerHTML = `
      <div class="approval-header">
        <div class="approval-badge">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
          <span>Authorization Required</span>
        </div>
        <span class="approval-tool">${escapeHtml(data.toolName)}</span>
      </div>
      <div class="approval-title">${escapeHtml(data.title || "Authorization Request")}</div>
      <div class="approval-desc">${escapeHtml(data.description || "")}</div>
      ${argsJson ? `<pre class="approval-args"><code>${escapeHtml(argsJson)}</code></pre>` : ""}
      <div class="approval-actions" id="approval-actions-${data.id}">
        <button type="button" class="btn-approval btn-allow" data-id="${data.id}">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
          <span>Allow</span>
        </button>
        <button type="button" class="btn-approval btn-deny" data-id="${data.id}">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          <span>Deny</span>
        </button>
      </div>
    `;

    const allowBtn = card.querySelector(".btn-allow");
    const denyBtn = card.querySelector(".btn-deny");
    const actionsEl = card.querySelector(`#approval-actions-${data.id}`);

    async function submitDecision(decision) {
      if (allowBtn) allowBtn.disabled = true;
      if (denyBtn) denyBtn.disabled = true;
      if (actionsEl) {
        actionsEl.innerHTML = `<span class="approval-resolving">Submitting ${decision === "allow" ? "approval" : "denial"}...</span>`;
      }

      try {
        const resp = await fetch(`/api/approvals/${data.id}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ decision }),
        });
        if (!resp.ok) {
          const errText = await resp.text();
          throw new Error(errText);
        }
      } catch (err) {
        if (actionsEl) {
          actionsEl.innerHTML = `<span class="approval-error">Failed: ${escapeHtml(err.message)}</span>`;
        }
      }
    }

    if (allowBtn) {
      allowBtn.addEventListener("click", () => submitDecision("allow"));
    }
    if (denyBtn) {
      denyBtn.addEventListener("click", () => submitDecision("deny"));
    }

    return card;
  }

  function createProgressIndicator(container, initialText = "Thinking...") {
    const el = document.createElement("div");
    el.className = "turn-progress-indicator";
    el.innerHTML = `
      <div class="progress-spinner-wrap">
        <svg class="cycling-circle" viewBox="0 0 24 24">
          <circle class="track" cx="12" cy="12" r="9"></circle>
          <circle class="head" cx="12" cy="12" r="9"></circle>
        </svg>
      </div>
      <div class="progress-info">
        <span class="progress-status-text">${escapeHtml(initialText)}</span>
        <span class="progress-dots">
          <span class="dot-bounce"></span>
          <span class="dot-bounce"></span>
          <span class="dot-bounce"></span>
        </span>
      </div>
    `;
    container.appendChild(el);
    return {
      element: el,
      setText(text) {
        const label = el.querySelector(".progress-status-text");
        if (label) label.textContent = text;
        if (container.lastElementChild !== el) {
          container.appendChild(el);
        }
        messagesStream.scrollTop = messagesStream.scrollHeight;
      },
      remove() {
        if (el && el.parentNode) {
          el.remove();
        }
      },
    };
  }

  // 9. Send Message Stream Handling
  chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const prompt = userInput.value.trim();
    if (!prompt || isGenerating) return;

    userInput.value = "";
    userInput.style.height = "auto";
    appendUserMessage(prompt);

    isGenerating = true;
    sendBtn.disabled = true;
    sendBtn.classList.add("btn-loading");
    sendBtn.innerHTML = `
      <svg class="btn-spinner" width="16" height="16" viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-dasharray="24 45"></circle>
      </svg>
    `;

    // Create assistant message row, turn content, and progress indicator
    const turnContent = createAssistantRow();
    const progressIndicator = createProgressIndicator(turnContent, "Analyzing request & screen memory...");
    let activeTextBubble = null;
    let activeBubbleText = "";
    let currentToolGroupEl = null;

    let thinkingStartTime = Date.now();
    let thinkingInterval = null;
    let accumulatedReasoning = "";

    // Always create the Thinking Drawer so the user sees real-time reasoning and planning
    const currentThinkingDrawer = document.createElement("details");
    currentThinkingDrawer.className = "thinking-drawer";
    currentThinkingDrawer.open = true;
    currentThinkingDrawer.innerHTML = `
      <summary class="thinking-drawer-summary">
        <div class="thinking-left">
          <span class="thinking-pulse-dot"></span>
          <span class="thinking-label">Thinking (<span class="thinking-timer">0s</span>)</span>
        </div>
        <svg class="thinking-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
      </summary>
      <div class="thinking-drawer-body">Analyzing request, evaluating memory parameters, and planning tool execution...</div>
    `;
    turnContent.appendChild(currentThinkingDrawer);

    thinkingInterval = setInterval(() => {
      const elapsed = Math.round((Date.now() - thinkingStartTime) / 1000);
      const timerEl = currentThinkingDrawer?.querySelector(".thinking-timer");
      if (timerEl) timerEl.textContent = `${elapsed}s`;
    }, 1000);

    function appendThinkingNote(text) {
      if (!currentThinkingDrawer) return;
      const body = currentThinkingDrawer.querySelector(".thinking-drawer-body");
      if (body) {
        body.textContent += `\n• ${text}`;
        body.scrollTop = body.scrollHeight;
      }
    }

    function finalizeThinking() {
      if (thinkingInterval) {
        clearInterval(thinkingInterval);
        thinkingInterval = null;
      }
      if (currentThinkingDrawer) {
        const elapsed = Math.max(1, Math.round((Date.now() - thinkingStartTime) / 1000));
        const label = currentThinkingDrawer.querySelector(".thinking-label");
        const dot = currentThinkingDrawer.querySelector(".thinking-pulse-dot");
        if (dot) dot.style.display = "none";
        if (label) label.textContent = `Thinking for ${elapsed}s`;
        currentThinkingDrawer.open = false; // Auto-collapse when answer begins streaming
      }
    }

    try {
      const selectedModelSetting = quickModelSelect?.value || localStorage.getItem("enheduanna_model") || "muse-spark-1.3";
      const isTwoModel = selectedModelSetting === "two-model";
      const modelName = isTwoModel ? "muse-spark-1.3" : selectedModelSetting;
      const reasoningEffort = quickReasoningSelect?.value || localStorage.getItem("enheduanna_reasoning_effort") || "high";
      const apiKey = localStorage.getItem("enheduanna_api_key") || undefined;
      const baseUrl = localStorage.getItem("enheduanna_base_url") || undefined;

      const response = await fetch("/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          sessionId: activeSessionId,
          message: prompt,
          options: {
            modelName,
            reasoningEffort,
            enableTwoModelRouting: isTwoModel,
            apiKey,
            baseUrl,
          },
        }),
      });

      if (!response.ok) {
        progressIndicator.remove();
        const err = await response.text();
        const errBubble = document.createElement("div");
        errBubble.className = "message-bubble";
        errBubble.textContent = `[Error: ${err}]`;
        turnContent.appendChild(errBubble);
        isGenerating = false;
        sendBtn.disabled = false;
        sendBtn.classList.remove("btn-loading");
        sendBtn.innerHTML = `
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
        `;
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop() || "";

        for (const block of lines) {
          const trimmed = block.trim();
          if (!trimmed) continue;

          let eventType = "message";
          let dataStr = "";

          for (const line of trimmed.split("\n")) {
            if (line.startsWith("event: ")) {
              eventType = line.substring(7).trim();
            } else if (line.startsWith("data: ")) {
              dataStr = line.substring(6).trim();
            }
          }

          if (!dataStr) continue;

          try {
            const data = JSON.parse(dataStr);

            if (eventType === "reasoning") {
              const body = currentThinkingDrawer.querySelector(".thinking-drawer-body");
              if (body) {
                if (!accumulatedReasoning) body.textContent = "";
                accumulatedReasoning += data.text;
                body.textContent = accumulatedReasoning;
              }
              const elapsed = Math.round((Date.now() - thinkingStartTime) / 1000);
              progressIndicator.setText(`Thinking & Reasoning (${elapsed}s)...`);
              messagesStream.scrollTop = messagesStream.scrollHeight;
            } else if (eventType === "step_narration") {
              appendThinkingNote(`Plan: ${data.text}`);
            } else if (eventType === "step_start") {
              appendThinkingNote(
                data.isSynthesis
                  ? `Step ${data.step}: Synthesizing final answer from evidence (${data.model || "synthesis"})...`
                  : `Step ${data.step}: Formulating plan with ${data.model || "agent"}...`
              );
              let stepBadge = turnContent.querySelector(".step-indicator-badge");
              if (!stepBadge) {
                stepBadge = document.createElement("div");
                stepBadge.className = "step-indicator-badge";
                turnContent.insertBefore(stepBadge, turnContent.firstChild);
              }
              stepBadge.textContent = data.isSynthesis
                ? `Synthesizing final answer... (Step ${data.step}/${data.maxSteps})`
                : `Step ${data.step} of ${data.maxSteps}`;

              progressIndicator.setText(
                data.isSynthesis
                  ? `Synthesizing final answer (Step ${data.step}/${data.maxSteps})...`
                  : `Step ${data.step} of ${data.maxSteps}: Running reasoning...`
              );
            } else if (eventType === "tool_group_start") {
              const toolNames = (data.toolCalls || []).map((t) => t.name).join(", ");
              appendThinkingNote(`Executing ${data.count || 1} parallel tool(s): ${toolNames || "tool"}`);
              // End text bubble; create group card for parallel tools
              activeTextBubble = null;
              activeBubbleText = "";

              currentToolGroupEl = document.createElement("div");
              currentToolGroupEl.className = "tool-group-card";
              currentToolGroupEl.id = `tool-group-step-${data.step}`;

              const count = data.count || 1;
              const groupHeader = document.createElement("div");
              groupHeader.className = "tool-group-header";
              groupHeader.id = `tool-group-header-step-${data.step}`;
              groupHeader.innerHTML = `
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                <span>${count > 1 ? `${count} parallel tool calls running...` : `Running tool call...`}</span>
              `;
              currentToolGroupEl.appendChild(groupHeader);
              turnContent.appendChild(currentToolGroupEl);

              progressIndicator.setText(
                count > 1
                  ? `Executing ${count} parallel tools concurrently...`
                  : `Executing tool: ${data.toolCalls?.[0]?.name || "tool"}...`
              );
              messagesStream.scrollTop = messagesStream.scrollHeight;
            } else if (eventType === "tool_call_start") {
              const chip = createToolChip(data.id, data.name, data.args);
              if (currentToolGroupEl) {
                currentToolGroupEl.appendChild(chip);
              } else {
                turnContent.appendChild(chip);
              }
              progressIndicator.setText(`Executing ${data.name}...`);
              messagesStream.scrollTop = messagesStream.scrollHeight;
            } else if (eventType === "tool_call_done") {
              appendInlineToolResult(data.id, data.name, data.resultPreview, {
                isError: data.isError,
                isRepeated: data.isRepeated,
                durationMs: data.durationMs,
                hasImage: data.hasImage,
                imageUrl: data.imageUrl,
              });
              progressIndicator.setText(`Finished ${data.name}, processing...`);
            } else if (eventType === "approval_required") {
              const approvalCard = createApprovalCard(data);
              if (currentToolGroupEl) {
                currentToolGroupEl.appendChild(approvalCard);
              } else {
                turnContent.appendChild(approvalCard);
              }
              progressIndicator.setText(`Waiting for your authorization on ${data.toolName}...`);
              messagesStream.scrollTop = messagesStream.scrollHeight;
            } else if (eventType === "approval_resolved") {
              const card = document.getElementById(`approval-${data.id}`);
              if (card) {
                const actionsEl = card.querySelector(".approval-actions");
                if (actionsEl) {
                  if (data.decision === "approved") {
                    actionsEl.innerHTML = `
                      <div class="approval-result-status status-allowed">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
                        <span>Access Granted by You</span>
                      </div>
                    `;
                  } else {
                    actionsEl.innerHTML = `
                      <div class="approval-result-status status-denied">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                        <span>Access Denied by You</span>
                      </div>
                    `;
                  }
                }
              }
              progressIndicator.setText(`Authorization resolved (${data.decision}). Continuing execution...`);
              messagesStream.scrollTop = messagesStream.scrollHeight;
            } else if (eventType === "tool_group_done") {
              appendThinkingNote(`Tools completed in ${data.wallClockMs}ms. Cross-referencing findings...`);
              const headerEl = document.getElementById(`tool-group-header-step-${data.step}`);
              if (headerEl) {
                const count = data.callCount || 1;
                headerEl.innerHTML = `
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
                  <span>${count > 1 ? `${count} parallel tool calls (${data.wallClockMs}ms wall-clock)` : `Tool call completed (${data.wallClockMs}ms)`}</span>
                `;
              }
              progressIndicator.setText(`Tool group finished (${data.wallClockMs}ms). Formulating next step...`);
            } else if (eventType === "step_cap_reached") {
              const capEl = document.createElement("div");
              capEl.className = "step-cap-warning";
              capEl.innerHTML = `
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                <span>Step limit reached (${data.maxSteps}/${data.maxSteps}) — synthesizing final answer</span>
              `;
              turnContent.appendChild(capEl);
              progressIndicator.setText(`Synthesizing final answer from available evidence...`);
              messagesStream.scrollTop = messagesStream.scrollHeight;
            } else if (eventType === "delta") {
              finalizeThinking();
              // Final answer started streaming: remove the progress indicator and collapse intermediate tool clutter
              progressIndicator.remove();

              if (!activeTextBubble) {
                collapseEvidence(turnContent);
                activeTextBubble = document.createElement("div");
                activeTextBubble.className = "message-bubble";
                turnContent.appendChild(activeTextBubble);
                activeBubbleText = "";
              }
              activeBubbleText += data.text;
              activeTextBubble.innerHTML = renderMarkdown(activeBubbleText);
              messagesStream.scrollTop = messagesStream.scrollHeight;
            } else if (eventType === "error") {
              finalizeThinking();
              progressIndicator.remove();
              const errEl = document.createElement("div");
              errEl.className = "message-bubble";
              errEl.style.color = "var(--accent-red)";
              errEl.textContent = `[Error: ${data.error}]`;
              turnContent.appendChild(errEl);
            } else if (eventType === "done") {
              finalizeThinking();
              progressIndicator.remove();
              collapseEvidence(turnContent);
              await loadSessions();
            }
          } catch {}
        }
      }
    } catch (err) {
      progressIndicator.remove();
      const errBubble = document.createElement("div");
      errBubble.className = "message-bubble";
      errBubble.style.color = "var(--accent-red)";
      errBubble.textContent = `[Request failed: ${err.message}]`;
      turnContent.appendChild(errBubble);
    } finally {
      progressIndicator.remove();
      isGenerating = false;
      sendBtn.disabled = false;
      sendBtn.classList.remove("btn-loading");
      sendBtn.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
      `;
      userInput.focus();
    }
  });

  // Auto-resize input textarea & Enter-to-send
  userInput.addEventListener("input", () => {
    userInput.style.height = "auto";
    userInput.style.height = `${Math.min(userInput.scrollHeight, 160)}px`;
  });

  userInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      chatForm.dispatchEvent(new Event("submit"));
    }
  });

  // Prompt template chips
  document.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      userInput.value = chip.dataset.prompt;
      userInput.focus();
      chatForm.dispatchEvent(new Event("submit"));
    });
  });

  // Quick Selectors in Header
  if (quickModelSelect) {
    quickModelSelect.addEventListener("change", () => {
      localStorage.setItem("enheduanna_model", quickModelSelect.value);
      if (settingModelSelect) {
        if (["muse-spark-1.3", "muse-wonder-1.0", "two-model"].includes(quickModelSelect.value)) {
          settingModelSelect.value = quickModelSelect.value;
          if (customModelGroup) customModelGroup.style.display = "none";
        }
      }
      if (activeProviderLabel) {
        activeProviderLabel.textContent = `META (${quickModelSelect.value})`;
      }
    });
  }

  if (quickReasoningSelect) {
    quickReasoningSelect.addEventListener("change", () => {
      localStorage.setItem("enheduanna_reasoning_effort", quickReasoningSelect.value);
      if (settingReasoningEffort) settingReasoningEffort.value = quickReasoningSelect.value;
    });
  }

  if (settingModelSelect) {
    settingModelSelect.addEventListener("change", () => {
      if (customModelGroup) {
        customModelGroup.style.display = settingModelSelect.value === "custom" ? "block" : "none";
      }
    });
  }

  // Settings Modal
  settingsBtn.addEventListener("click", async () => {
    settingsModal.classList.remove("hidden");

    try {
      const res = await apiFetch("/api/config");
      if (res.ok) {
        const cfg = await res.json();
        settingProvider.value = cfg.provider || "meta";
        settingBaseUrl.value = localStorage.getItem("enheduanna_base_url") || cfg.baseUrl || "";

        const currentModel = localStorage.getItem("enheduanna_model") || cfg.modelName || "muse-spark-1.3";
        if (["muse-spark-1.3", "muse-wonder-1.0", "two-model"].includes(currentModel)) {
          settingModelSelect.value = currentModel;
          if (customModelGroup) customModelGroup.style.display = "none";
        } else {
          settingModelSelect.value = "custom";
          settingModelName.value = currentModel;
          if (customModelGroup) customModelGroup.style.display = "block";
        }

        const currentReasoning = localStorage.getItem("enheduanna_reasoning_effort") || cfg.reasoningEffort || "high";
        if (settingReasoningEffort) settingReasoningEffort.value = currentReasoning;
      }
    } catch {}
  });

  closeSettingsBtn.addEventListener("click", () => {
    settingsModal.classList.add("hidden");
  });

  saveSettingsBtn.addEventListener("click", async () => {
    let chosenModel = settingModelSelect ? settingModelSelect.value : "muse-spark-1.3";
    if (chosenModel === "custom") {
      chosenModel = settingModelName.value.trim() || "muse-spark-1.3";
    }

    const chosenReasoning = settingReasoningEffort ? settingReasoningEffort.value : "high";
    localStorage.setItem("enheduanna_model", chosenModel);
    localStorage.setItem("enheduanna_reasoning_effort", chosenReasoning);

    if (quickModelSelect) {
      if (["muse-spark-1.3", "muse-wonder-1.0", "two-model"].includes(chosenModel)) {
        quickModelSelect.value = chosenModel;
      }
    }
    if (quickReasoningSelect) quickReasoningSelect.value = chosenReasoning;

    const payload = {
      provider: settingProvider.value,
      baseUrl: settingBaseUrl.value.trim(),
      modelName: chosenModel === "two-model" ? "muse-spark-1.3" : chosenModel,
      reasoningEffort: chosenReasoning,
      enableTwoModelRouting: chosenModel === "two-model",
    };

    if (settingBaseUrl.value.trim()) {
      localStorage.setItem("enheduanna_base_url", settingBaseUrl.value.trim());
    }

    if (settingApiKey.value.trim()) {
      payload.apiKey = settingApiKey.value.trim();
      localStorage.setItem("enheduanna_api_key", settingApiKey.value.trim());
    }

    try {
      const res = await apiFetch("/api/config", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        settingsModal.classList.add("hidden");
        settingApiKey.value = "";
        await loadHealth();
      }
    } catch (err) {
      alert(`Failed to save settings: ${err.message}`);
    }
  });

  function escapeHtml(text) {
    if (!text) return "";
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Initialize
  bootstrap();
})();
