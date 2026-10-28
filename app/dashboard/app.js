// Enheduanna Dashboard Client Logic

(function () {
  let authToken = "";
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
  const modelNameText = document.getElementById("model-name-text");
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
  const tokenPromptModal = document.getElementById("token-prompt-modal");
  const initialTokenInput = document.getElementById("initial-token-input");
  const submitTokenBtn = document.getElementById("submit-token-btn");

  // Settings inputs
  const settingProvider = document.getElementById("setting-provider");
  const settingBaseUrl = document.getElementById("setting-base-url");
  const settingModelName = document.getElementById("setting-model-name");
  const settingApiKey = document.getElementById("setting-api-key");
  const settingLocalToken = document.getElementById("setting-local-token");

  // 1. Authentication Initialization
  function initAuth() {
    const urlParams = new URLSearchParams(window.location.search);
    const queryToken = urlParams.get("token");

    if (queryToken) {
      authToken = queryToken;
      sessionStorage.setItem("enheduanna_token", queryToken);
      // Clean URL query parameter for security
      window.history.replaceState({}, document.title, window.location.pathname);
    } else {
      authToken = sessionStorage.getItem("enheduanna_token") || "";
    }

    if (!authToken) {
      tokenPromptModal.classList.remove("hidden");
    } else {
      bootstrap();
    }
  }

  submitTokenBtn.addEventListener("click", () => {
    const val = initialTokenInput.value.trim();
    if (val) {
      authToken = val;
      sessionStorage.setItem("enheduanna_token", val);
      tokenPromptModal.classList.add("hidden");
      bootstrap();
    }
  });

  // 2. HTTP Helper with Auth
  async function apiFetch(endpoint, options = {}) {
    const headers = {
      ...(options.headers || {}),
      Authorization: `Bearer ${authToken}`,
      "Content-Type": "application/json",
    };

    const res = await fetch(endpoint, { ...options, headers });
    if (res.status === 401) {
      tokenPromptModal.classList.remove("hidden");
      throw new Error("Unauthorized");
    }
    return res;
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

      modelNameText.textContent = data.modelConfig.modelName;
      activeProviderLabel.textContent = `${data.modelConfig.provider.toUpperCase()} (${data.modelConfig.modelName})`;

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

  // 6. Live Trace SSE Stream
  function connectTraceStream() {
    if (traceSource) traceSource.close();

    traceSource = new EventSource(`/trace?token=${encodeURIComponent(authToken)}`);

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

    card.innerHTML = `
      <div class="trace-top">
        <span class="trace-badge">${evt.source || "system"}</span>
        <span>${time} ${latency ? `• ${latency}` : ""}</span>
      </div>
      <div class="trace-summary">${escapeHtml(evt.title)}</div>
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

  function renderSessionMessages(messages) {
    messagesStream.innerHTML = "";
    const visibleMessages = messages.filter((m) => m.role !== "system");

    if (visibleMessages.length === 0) {
      messagesStream.appendChild(chatWelcome);
      chatWelcome.style.display = "block";
      return;
    }

    chatWelcome.style.display = "none";
    for (const msg of visibleMessages) {
      if (msg.role === "user") {
        appendUserMessage(msg.content);
      } else if (msg.role === "assistant") {
        appendAssistantMessage(msg.content, msg.tool_calls);
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

  function appendAssistantMessage(text, toolCalls) {
    chatWelcome.style.display = "none";
    const row = document.createElement("div");
    row.className = "message-row assistant";
    row.innerHTML = `
      <div class="message-header">Enheduanna</div>
      <div class="message-bubble">${escapeHtml(text || "")}</div>
    `;

    if (toolCalls && toolCalls.length > 0) {
      for (const tc of toolCalls) {
        const chip = createToolChip(tc.id, tc.function.name, tc.function.arguments);
        row.appendChild(chip);
      }
    }

    messagesStream.appendChild(row);
    messagesStream.scrollTop = messagesStream.scrollHeight;
    return row.querySelector(".message-bubble");
  }

  function createToolChip(id, name, argsStr) {
    const chip = document.createElement("div");
    chip.className = "tool-chip";
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
      <div class="tool-chip-header">
        <span class="tool-chip-name">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
          ${escapeHtml(name)}
        </span>
        <span class="tool-chip-status" id="chip-status-${id}">Executing...</span>
      </div>
      <div class="tool-chip-body" id="chip-body-${id}">Arguments:\n${escapeHtml(parsedArgs)}</div>
    `;

    chip.querySelector(".tool-chip-header").addEventListener("click", () => {
      const body = chip.querySelector(".tool-chip-body");
      body.style.display = body.style.display === "none" ? "block" : "none";
    });

    return chip;
  }

  function appendInlineToolResult(callId, name, resultText) {
    const statusEl = document.getElementById(`chip-status-${callId}`);
    const bodyEl = document.getElementById(`chip-body-${callId}`);

    if (statusEl) {
      statusEl.textContent = "Done";
      statusEl.style.color = "var(--accent-green)";
    }
    if (bodyEl) {
      bodyEl.textContent += `\n\nResult:\n${resultText}`;
    }
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

    // Create assistant message row
    const bubble = appendAssistantMessage("");
    let currentBubbleText = "";

    try {
      const response = await fetch("/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify({
          sessionId: activeSessionId,
          message: prompt,
        }),
      });

      if (!response.ok) {
        const err = await response.text();
        bubble.textContent = `[Error: ${err}]`;
        isGenerating = false;
        sendBtn.disabled = false;
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

            if (eventType === "delta") {
              currentBubbleText += data.text;
              bubble.textContent = currentBubbleText;
              messagesStream.scrollTop = messagesStream.scrollHeight;
            } else if (eventType === "tool_call_start") {
              const chip = createToolChip(data.id, data.name, data.args);
              bubble.parentElement.appendChild(chip);
            } else if (eventType === "tool_call_done") {
              appendInlineToolResult(data.id, data.name, data.resultPreview);
            } else if (eventType === "error") {
              currentBubbleText += `\n[Error: ${data.error}]`;
              bubble.textContent = currentBubbleText;
            } else if (eventType === "done") {
              await loadSessions();
            }
          } catch {}
        }
      }
    } catch (err) {
      bubble.textContent = `[Request failed: ${err.message}]`;
    } finally {
      isGenerating = false;
      sendBtn.disabled = false;
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

  // 10. Settings Modal
  settingsBtn.addEventListener("click", async () => {
    settingsModal.classList.remove("hidden");
    settingLocalToken.value = authToken;

    try {
      const res = await apiFetch("/api/config");
      if (res.ok) {
        const cfg = await res.json();
        settingProvider.value = cfg.provider || "meta";
        settingBaseUrl.value = cfg.baseUrl || "";
        settingModelName.value = cfg.modelName || "";
      }
    } catch {}
  });

  closeSettingsBtn.addEventListener("click", () => {
    settingsModal.classList.add("hidden");
  });

  saveSettingsBtn.addEventListener("click", async () => {
    const payload = {
      provider: settingProvider.value,
      baseUrl: settingBaseUrl.value.trim(),
      modelName: settingModelName.value.trim(),
    };

    if (settingApiKey.value.trim()) {
      payload.apiKey = settingApiKey.value.trim();
    }

    if (settingLocalToken.value.trim()) {
      authToken = settingLocalToken.value.trim();
      sessionStorage.setItem("enheduanna_token", authToken);
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
  initAuth();
})();
