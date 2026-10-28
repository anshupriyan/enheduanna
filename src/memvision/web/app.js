/**
 * mem-vision-mcp Dashboard Client
 * Real-time continuous desktop memory viewer, search & AI chat assistant.
 */

// Application State
const state = {
  viewMode: 'timeline',
  activeFilter: 'all',
  searchQuery: '',
  autoRefresh: true,
  refreshTimer: null,
  captures: [],
  sessions: [],
  selectedCapture: null,
};

// DOM Elements
const elements = {
  capturesGrid: document.getElementById('captures-grid'),
  searchInput: document.getElementById('search-input'),
  searchClearBtn: document.getElementById('search-clear-btn'),
  filterChips: document.getElementById('filter-chips'),
  statTotalCaptures: document.getElementById('stat-total-captures'),
  statDbSize: document.getElementById('stat-db-size'),
  btnToggleAutorefresh: document.getElementById('btn-toggle-autorefresh'),
  btnViewTimeline: document.getElementById('btn-view-timeline'),
  btnViewSessions: document.getElementById('btn-view-sessions'),
  resultsCount: document.getElementById('results-count'),
  streamTitle: document.getElementById('stream-title'),
  lastUpdatedText: document.getElementById('last-updated-text'),
  
  // Modal
  modal: document.getElementById('capture-modal'),
  btnCloseModal: document.getElementById('btn-close-modal'),
  modalScreenshotImg: document.getElementById('modal-screenshot-img'),
  modalAppBadge: document.getElementById('modal-app-badge'),
  modalWindowTitle: document.getElementById('modal-window-title'),
  modalCaptureId: document.getElementById('modal-capture-id'),
  modalTimestamp: document.getElementById('modal-timestamp'),
  modalPhash: document.getElementById('modal-phash'),
  modalUrlContainer: document.getElementById('modal-url-container'),
  modalUrlLink: document.getElementById('modal-url-link'),
  modalUrlText: document.getElementById('modal-url-text'),
  modalFileContainer: document.getElementById('modal-file-container'),
  modalFileText: document.getElementById('modal-file-text'),
  modalOcrText: document.getElementById('modal-ocr-text'),
  modalOcrCharCount: document.getElementById('modal-ocr-char-count'),
  btnCopyOcr: document.getElementById('btn-copy-ocr'),

  // Chat
  chatSidebar: document.getElementById('chat-sidebar'),
  btnOpenChat: document.getElementById('btn-open-chat'),
  btnCloseChat: document.getElementById('btn-close-chat'),
  chatMessages: document.getElementById('chat-messages'),
  chatForm: document.getElementById('chat-form'),
  chatTextarea: document.getElementById('chat-textarea'),
  aiModelBadge: document.getElementById('ai-model-badge'),
};

// App Initialization
document.addEventListener('DOMContentLoaded', () => {
  initEventListeners();
  initModalLightDismiss();
  fetchStats();
  fetchCaptures();
  startAutoRefresh();
});

function initEventListeners() {
  // Search input with debounce
  let searchDebounceTimeout;
  elements.searchInput.addEventListener('input', (e) => {
    const val = e.target.value.trim();
    elements.searchClearBtn.classList.toggle('hidden', val.length === 0);
    clearTimeout(searchDebounceTimeout);
    searchDebounceTimeout = setTimeout(() => {
      state.searchQuery = val;
      fetchCaptures();
    }, 280);
  });

  elements.searchClearBtn.addEventListener('click', () => {
    elements.searchInput.value = '';
    elements.searchClearBtn.classList.add('hidden');
    state.searchQuery = '';
    fetchCaptures();
  });

  // Filter chips
  elements.filterChips.addEventListener('click', (e) => {
    const chip = e.target.closest('.chip');
    if (!chip) return;
    elements.filterChips.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
    state.activeFilter = chip.dataset.filter || 'all';
    if (state.viewMode === 'sessions') {
      renderSessions();
    } else {
      renderCaptures();
    }
  });

  // View mode toggle
  if (elements.btnViewTimeline && elements.btnViewSessions) {
    elements.btnViewTimeline.addEventListener('click', () => {
      state.viewMode = 'timeline';
      elements.btnViewTimeline.classList.add('active');
      elements.btnViewSessions.classList.remove('active');
      fetchCaptures();
    });

    elements.btnViewSessions.addEventListener('click', () => {
      state.viewMode = 'sessions';
      elements.btnViewSessions.classList.add('active');
      elements.btnViewTimeline.classList.remove('active');
      fetchSessions();
    });
  }

  // Auto-refresh toggle
  elements.btnToggleAutorefresh.addEventListener('click', () => {
    state.autoRefresh = !state.autoRefresh;
    elements.btnToggleAutorefresh.classList.toggle('active', state.autoRefresh);
    if (state.autoRefresh) {
      startAutoRefresh();
      fetchCaptures();
    } else {
      stopAutoRefresh();
    }
  });

  // Modal close
  elements.btnCloseModal.addEventListener('click', () => {
    elements.modal.close();
  });

  // Copy OCR text
  elements.btnCopyOcr.addEventListener('click', async () => {
    const text = elements.modalOcrText.textContent;
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      const span = elements.btnCopyOcr.querySelector('span');
      const original = span.textContent;
      span.textContent = 'Copied!';
      setTimeout(() => { span.textContent = original; }, 2000);
    } catch (err) {
      console.error('Clipboard copy failed:', err);
    }
  });

  // Chat toggle
  elements.btnOpenChat.addEventListener('click', () => {
    elements.chatSidebar.classList.remove('collapsed');
    elements.chatTextarea.focus();
  });

  elements.btnCloseChat.addEventListener('click', () => {
    elements.chatSidebar.classList.add('collapsed');
  });

  // Chat submit
  elements.chatForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const message = elements.chatTextarea.value.trim();
    if (!message) return;
    sendChatMessage(message);
    elements.chatTextarea.value = '';
  });

  // Chat Enter to submit (Shift+Enter for newline)
  elements.chatTextarea.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      elements.chatForm.dispatchEvent(new Event('submit'));
    }
  });
}

/**
 * Modern modal light dismiss fallback for browsers lacking native closedby="any"
 */
function initModalLightDismiss() {
  if (!('closedBy' in HTMLDialogElement.prototype)) {
    const dialog = elements.modal;
    const isOutside = (e) => {
      const r = dialog.getBoundingClientRect();
      return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
    };
    let pressedOutside = false;
    dialog.addEventListener('pointerdown', (e) => { pressedOutside = isOutside(e); });
    dialog.addEventListener('pointerup', (e) => {
      if (pressedOutside && isOutside(e)) dialog.close();
    });
  }
}

// Auto-refresh control
function startAutoRefresh() {
  stopAutoRefresh();
  state.refreshTimer = setInterval(() => {
    if (state.autoRefresh && !state.searchQuery && !elements.modal.open) {
      fetchCaptures(true);
      fetchStats();
    }
  }, 4000);
}

function stopAutoRefresh() {
  if (state.refreshTimer) {
    clearInterval(state.refreshTimer);
    state.refreshTimer = null;
  }
}

// Fetch Storage Statistics
async function fetchStats() {
  try {
    const res = await fetch('/api/stats');
    if (!res.ok) return;
    const data = await res.json();
    if (data.total_captures !== undefined) {
      elements.statTotalCaptures.textContent = data.total_captures.toLocaleString();
    }
    if (data.database_size_mb !== undefined) {
      elements.statDbSize.textContent = `${data.database_size_mb} MB`;
    }
  } catch (e) {
    console.error('Failed to fetch stats:', e);
  }
}

// Fetch Recent or Searched Captures
async function fetchCaptures(silent = false) {
  try {
    let url = '/api/recent?limit=48';
    if (state.searchQuery) {
      url = `/api/search?q=${encodeURIComponent(state.searchQuery)}&limit=48`;
    }

    const res = await fetch(url);
    if (!res.ok) throw new Error('API response not OK');
    const data = await res.json();
    state.captures = data;
    renderCaptures();
    
    const now = new Date();
    elements.lastUpdatedText.textContent = `Updated ${now.toLocaleTimeString()}`;
  } catch (err) {
    console.error('Error fetching captures:', err);
    if (!silent) {
      elements.capturesGrid.innerHTML = `
        <div class="empty-state">
          <p>⚠️ Unable to fetch captures from local memory service.</p>
        </div>
      `;
    }
  }
}

// Filter and Render Cards
function renderCaptures() {
  let list = state.captures;

  if (state.activeFilter !== 'all') {
    list = list.filter(c => (c.app_name || '').toLowerCase() === state.activeFilter.toLowerCase());
  }

  elements.resultsCount.textContent = `${list.length} captures`;
  elements.streamTitle.textContent = state.searchQuery 
    ? `Search Results for "${state.searchQuery}"` 
    : 'Recent Timeline';

  if (list.length === 0) {
    elements.capturesGrid.innerHTML = `
      <div class="empty-state">
        <svg viewBox="0 0 24 24" width="48" height="48" stroke="currentColor" stroke-width="1.5" fill="none">
          <circle cx="12" cy="12" r="10"/>
          <line x1="8" y1="12" x2="16" y2="12"/>
        </svg>
        <p>No captures found for the selected criteria.</p>
      </div>
    `;
    return;
  }

  elements.capturesGrid.innerHTML = list.map(c => {
    const timeFormatted = formatTimeAgo(c.timestamp);
    const ocrSnippet = highlightQuery(c.ocr_snippet || '', state.searchQuery);
    const appColor = getAppColorClass(c.app_name);

    return `
      <article class="capture-card" data-id="${c.id}" onclick="openCaptureDetail(${c.id})">
        <div class="card-thumb-container">
          <img class="card-thumb-img" src="/api/screenshot/${c.id}" alt="Screenshot #${c.id}" loading="lazy" onerror="this.src='/fallback.png'">
          <div class="card-badge-row">
            <div style="display: flex; align-items: center; gap: 0.35rem;">
              <span class="app-badge ${appColor}">${escapeHtml(c.app_name || 'desktop')}</span>
              ${c.is_spatially_masked ? `
                <span class="privacy-masked-badge" title="Restricted window masked: ${escapeHtml((c.spatial_masked_windows || []).join(', ') || 'Protected')}">
                  🔒 Masked
                </span>
              ` : ''}
            </div>
            <span class="time-badge">${timeFormatted}</span>
          </div>
        </div>
        <div class="card-body">
          <h4 class="card-title" title="${escapeHtml(c.window_title || '')}">${escapeHtml(c.window_title || 'Desktop Activity')}</h4>
          ${c.file_path ? `
            <div class="card-file-row" style="display: flex; align-items: center; gap: 0.35rem; font-size: 0.72rem; color: #a0aec0; margin-bottom: 0.35rem; font-family: monospace;" title="${escapeHtml(c.file_path)}">
              <span>📄</span>
              <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(c.file_path)}</span>
            </div>
          ` : ''}
          ${c.url ? `
            <div class="card-url-row">
              <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
                <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
              </svg>
              <a href="${escapeHtml(c.url)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">${escapeHtml(cleanUrlDisplay(c.url))}</a>
            </div>
          ` : ''}
          <p class="card-ocr-preview">${ocrSnippet || '<span class="text-subtle">No text detected</span>'}</p>
        </div>
      </article>
    `;
  }).join('');
}

// Fetch Clustered Sessions
async function fetchSessions() {
  try {
    const res = await fetch('/api/sessions?limit=30');
    if (!res.ok) throw new Error('API response not OK');
    state.sessions = await res.json();
    renderSessions();

    const now = new Date();
    elements.lastUpdatedText.textContent = `Updated ${now.toLocaleTimeString()}`;
  } catch (err) {
    console.error('Error fetching sessions:', err);
  }
}

// Render Focus Sessions
function renderSessions() {
  let list = state.sessions;
  if (state.activeFilter !== 'all') {
    list = list.filter(s => (s.app_name || '').toLowerCase() === state.activeFilter.toLowerCase());
  }

  elements.resultsCount.textContent = `${list.length} sessions`;
  elements.streamTitle.textContent = 'Clustered Focus Sessions';

  if (list.length === 0) {
    elements.capturesGrid.innerHTML = `
      <div class="empty-state">
        <p>No focus sessions recorded yet.</p>
      </div>
    `;
    return;
  }

  elements.capturesGrid.innerHTML = list.map(s => {
    const durMin = Math.round((s.duration_seconds / 60) * 10) / 10;
    const durStr = durMin >= 1 ? `${durMin}m` : `${s.duration_seconds}s`;
    const appColor = getAppColorClass(s.app_name);

    return `
      <article class="capture-card session-card" onclick="openCaptureDetail(${s.key_capture_id || 1})">
        <div class="card-thumb-container">
          <img class="card-thumb-img" src="/api/screenshot/${s.key_capture_id || 1}" alt="Session #${s.id}" loading="lazy" onerror="this.src='/fallback.png'">
          <div class="card-badge-row">
            <span class="app-badge ${appColor}">${escapeHtml(s.app_name || 'session')}</span>
            <div style="display: flex; gap: 0.3rem;">
              <span class="session-duration-tag">⏱️ ${durStr}</span>
              <span class="session-frames-tag">${s.capture_count} frames</span>
            </div>
          </div>
        </div>
        <div class="card-body">
          <h4 class="card-title" title="${escapeHtml(s.title || '')}">${escapeHtml(s.title || 'Focus Session')}</h4>
          ${s.url ? `
            <div class="card-url-row">
              <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
                <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
              </svg>
              <a href="${escapeHtml(s.url)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">${escapeHtml(cleanUrlDisplay(s.url))}</a>
            </div>
          ` : ''}
          <p class="card-ocr-preview"><span class="text-subtle">Keywords:</span> ${escapeHtml(s.summary_keywords || 'Activity recorded')}</p>
        </div>
      </article>
    `;
  }).join('');
}

// Open Capture in Detail Modal
async function openCaptureDetail(captureId) {
  try {
    const res = await fetch(`/api/capture/${captureId}`);
    if (!res.ok) return;
    const capture = await res.json();
    state.selectedCapture = capture;

    const maskedList = capture.metadata?.spatial_masked_windows || [];
    elements.modalAppBadge.textContent = capture.app_name || 'System';
    if (maskedList.length > 0) {
      elements.modalAppBadge.textContent += ` [🔒 Masked: ${maskedList.join(', ')}]`;
    }
    elements.modalWindowTitle.textContent = capture.window_title || 'Untitled Window';
    elements.modalCaptureId.textContent = `#${capture.id}`;
    elements.modalTimestamp.textContent = new Date(capture.timestamp).toLocaleString();
    elements.modalPhash.textContent = capture.phash ? capture.phash.substring(0, 16) : '--';
    
    // Tab URL
    if (capture.url) {
      elements.modalUrlContainer.classList.remove('hidden');
      elements.modalUrlLink.href = capture.url;
      elements.modalUrlText.textContent = capture.url;
    } else {
      elements.modalUrlContainer.classList.add('hidden');
    }

    // Resolved File Path
    if (capture.file_path && elements.modalFileContainer) {
      elements.modalFileContainer.classList.remove('hidden');
      elements.modalFileText.textContent = capture.file_path;
    } else if (elements.modalFileContainer) {
      elements.modalFileContainer.classList.add('hidden');
    }

    // OCR text
    const ocrText = capture.full_ocr_text || capture.ocr_text || 'No text extracted for this frame.';
    elements.modalOcrText.textContent = ocrText;
    elements.modalOcrCharCount.textContent = ocrText.length.toLocaleString();

    elements.modal.showModal();
  } catch (err) {
    console.error('Failed to open capture detail:', err);
  }
}

// AI Chat Interaction
async function sendChatMessage(query) {
  // Render user message bubble
  appendMessage('user', query);

  // Render assistant loading placeholder
  const loadingBubble = appendMessage('assistant', '<div class="spinner"></div>', true);

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query }),
    });

    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }

    const data = await res.json();
    loadingBubble.remove();

    let citationsHtml = '';
    if (data.citations && data.citations.length > 0) {
      citationsHtml = `
        <div class="citations-box">
          <span class="text-xs text-muted">Referenced Memories:</span>
          <div style="display: flex; gap: 0.35rem; flex-wrap: wrap;">
            ${data.citations.map(c => `
              <button class="citation-chip" onclick="openCaptureDetail(${c.id})">
                #${c.id} • ${escapeHtml(c.app_name || 'capture')}
              </button>
            `).join('')}
          </div>
        </div>
      `;
    }

    appendMessage('assistant', `
      <p>${escapeHtml(data.answer).replace(/\n/g, '<br>')}</p>
      ${citationsHtml}
    `);

    if (data.model_used) {
      elements.aiModelBadge.textContent = data.model_used;
    }

  } catch (err) {
    loadingBubble.remove();
    appendMessage('assistant', `⚠️ Error synthesizing memory: ${err.message}`);
  }
}

function appendMessage(sender, htmlContent, isLoading = false) {
  const msgDiv = document.createElement('div');
  msgDiv.className = `message ${sender}-message`;
  msgDiv.innerHTML = `<div class="msg-bubble">${htmlContent}</div>`;
  elements.chatMessages.appendChild(msgDiv);
  elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
  return msgDiv;
}

// Prompt pill handler
window.sendSuggestedPrompt = function(btn) {
  const text = btn.textContent;
  elements.chatTextarea.value = text;
  elements.chatForm.dispatchEvent(new Event('submit'));
};

// Utilities
function formatTimeAgo(isoString) {
  if (!isoString) return '--';
  const diff = Date.now() - new Date(isoString).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return `${Math.max(1, seconds)}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function cleanUrlDisplay(url) {
  try {
    const parsed = new URL(url);
    return parsed.hostname + (parsed.pathname.length > 1 ? parsed.pathname : '');
  } catch {
    return url;
  }
}

function highlightQuery(text, query) {
  if (!query) return escapeHtml(text);
  const escaped = escapeHtml(text);
  const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
  return escaped.replace(regex, '<span class="highlight">$1</span>');
}

function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function getAppColorClass(appName) {
  const name = (appName || '').toLowerCase();
  if (name.includes('code')) return 'border-indigo';
  if (name.includes('chrome') || name.includes('brave') || name.includes('edge')) return 'border-cyan';
  if (name.includes('powershell') || name.includes('cmd')) return 'border-purple';
  return '';
}
