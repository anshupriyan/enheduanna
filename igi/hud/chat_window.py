"""
IGI (𒅆) — Floating Companion HUD Window
Frameless, solid dark-grey professional window with live streaming, drag handling,
collapsible tool drawer, and dynamic multi-direction resizing.
"""

from __future__ import annotations

import threading
from typing import Optional
from PIL import Image

try:
    from PySide6.QtCore import Qt, QPoint, QRect, Signal, QObject, QTimer
    from PySide6.QtGui import QMouseEvent, QScreen, QGuiApplication, QCursor
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
        QLineEdit, QTextEdit, QApplication, QFrame, QSizeGrip, QSizePolicy
    )
except ImportError:
    pass

try:
    from .theme import QSS_STYLESHEET
    from .cards import ContextPreviewCard, QuickActionsBar
    from .stream_view import ChatStreamView
    from ..bridge.core_client import CoreClient
    from ..config import load_config, IgiConfig
except (ImportError, ValueError):
    from hud.theme import QSS_STYLESHEET
    from hud.cards import ContextPreviewCard, QuickActionsBar
    from hud.stream_view import ChatStreamView
    from bridge.core_client import CoreClient
    from config import load_config, IgiConfig


class StreamSignals(QObject):
    token_received = Signal(str)
    status_updated = Signal(str)
    turn_finished = Signal(str)
    event_received = Signal(str, object)
    guidance_highlight_requested = Signal(object, str, str, int)  # bbox, label, description, duration_ms
    walkthrough_blocks_ready = Signal(object, int)                 # blocks, duration_ms
    workflow_state_changed = Signal(str, str)                      # state, subtitle
    context_card_updated = Signal(object, str, str, object)        # crop, display_chip, ocr_text, window_context


# Edge flags for frameless window resizing
EDGE_NONE = 0
EDGE_LEFT = 1
EDGE_RIGHT = 2
EDGE_TOP = 4
EDGE_BOTTOM = 8
EDGE_MARGIN = 8


def extract_concept_from_prompt(prompt: str) -> str:
    """Extract core concept keywords from natural language user queries."""
    p = prompt.strip()
    low = p.lower()
    prefixes = [
        "can you mark all the", "can you mark the", "can you mark",
        "mark all the", "mark the", "mark",
        "can you highlight all the", "can you highlight the", "can you highlight",
        "help me understand these", "help me understand the", "help me understand",
        "use segmentation to highlight that", "use segmentation to highlight the", "use segmentation to highlight",
        "use segmentation to find", "use segmentation to show", "use segmentation to",
        "use segmentation",
        "highlight that", "highlight the", "highlight",
        "segment that", "segment the", "segment",
        "point to that", "point to the", "point to",
        "spotlight that", "spotlight the", "spotlight",
        "show me that", "show me the", "show me",
        "circle that", "circle the", "circle",
        "can you help me identify the", "can you help me find the", "can you help me locate the",
        "help me identify the", "help me find the", "help me locate the",
        "please find the", "please locate the", "please show me the",
        "vs code says i need to update but i cant find the",
        "vs code says i need to update but i can't find the",
        "vs code need update but i cant find the",
        "vs code need update but i can't find the",
        "where is the", "where's the", "where is", "where's",
        "find the", "find", "locate the", "locate", "identify the", "identify",
        "look for the", "look for", "search for the", "search for",
        "i cant find the", "i can't find the", "cant find the", "can't find the",
    ]
    for pref in prefixes:
        if low.startswith(pref):
            p = p[len(pref):].strip()
            low = p.lower()
            break

    suffixes = [
        "and explain stuff right next to it", "and explain stuff", "and explain",
        "right next to it", "next to it",
        "in realtime", "in real-time", "realtime",
        "that where is it", "where is it", "where is", "that where",
        "on my screen i cant find it", "on my screen i can't find it",
        "on screen i cant find it", "on screen i can't find it",
        "on screen that where is it", "on screen where is it",
        "i cant find it", "i can't find it",
        "on my screen please", "on screen please",
        "on my screen", "on screen",
        "i cannot find it", "cant find", "can't find",
        "pls", "plz", "please",
    ]
    for suff in suffixes:
        if low.endswith(suff):
            p = p[:-len(suff)].strip(" ?.,!\"'")
            low = p.lower()
            break

    p = p.strip(" ?.,!\"'")
    if not p or len(p) < 2:
        if "update" in prompt.lower():
            return "update button"
        elif "dollar" in prompt.lower() or "credit" in prompt.lower():
            return "dollar credit"
        elif "graph" in prompt.lower():
            return "graph"
        return prompt.strip()
    return p


def infer_concept_and_region(prompt: str) -> tuple[str, str]:
    """
    Extract target concept keyword and spatial region hint from user query.
    Brain -> Region Hint: ('top', 'sidebar', 'bottom', 'right', 'center', 'any').
    """
    concept = extract_concept_from_prompt(prompt)
    low_p = prompt.lower()

    if any(k in low_p for k in ("update", "restart", "tab", "title", "header", "address", "url", "top bar", "nav bar", "menu", "top")):
        region = "top"
    elif any(k in low_p for k in ("sidebar", "file tree", "explorer", "files", "folder", "channels", "left side", "left panel", "left")):
        region = "sidebar"
    elif any(k in low_p for k in ("terminal", "console", "reply", "compose", "bottom bar", "status bar", "taskbar", "bottom")):
        region = "bottom"
    elif any(k in low_p for k in ("inspector", "properties", "details", "right side", "right panel", "right")):
        region = "right"
    elif any(k in low_p for k in ("graph", "plot", "code", "editor", "document", "canvas", "center")):
        region = "center"
    else:
        region = "any"

    return concept, region


class IgiHudWindow(QWidget):
    """Frameless scalable solid dark-grey AI companion HUD with edge and corner resizing."""

    def __init__(
        self,
        config: Optional[IgiConfig] = None,
        projector: Optional[Any] = None,
        sam_router: Optional[Any] = None
    ):
        super().__init__()
        self.config = config or load_config()
        self.projector = projector
        self.sam_router = sam_router
        self.core_client = CoreClient(self.config)
        self.signals = StreamSignals()

        self.current_crop: Optional[Image.Image] = None
        self.current_ocr_text: str = ""
        self.current_window_title: str = ""
        self.current_process_name: str = ""
        self.current_window_context: Optional[Any] = None
        self._has_fresh_circle: bool = False
        self._live_session_active: bool = False
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._last_prompt: str = ""
        self._cancel_requested: bool = False

        # Reactive Visual Reasoning Loop state
        self._workflow_state: str = "IDLE"  # "IDLE", "AWAITING_REPLY_INPUT", "AWAITING_SEND", "COMPLETED"
        self._workflow_target_bbox: Optional[list] = None
        self._workflow_baseline_crop: Optional[Image.Image] = None
        self._workflow_context: str = ""
        self._workflow_draft_text: str = ""
        self._is_evaluating_tick: bool = False
        self._workflow_timer = QTimer(self)
        self._workflow_timer.setInterval(1200)
        self._workflow_timer.timeout.connect(self._on_workflow_tick)

        # Resizing & Dragging state
        self._drag_pos = QPoint()
        self._is_dragging_header = False
        self._current_edge = EDGE_NONE
        self._resize_start_pos = QPoint()
        self._resize_start_geo = QRect()
        self._is_expanded = False
        self._normal_geo: Optional[QRect] = None

        self._init_window_flags()
        self._init_ui()
        self._connect_signals()
        self.position_bottom_right()
        self.check_connection_status()

    def _init_window_flags(self):
        self.setObjectName("IgiHudWindow")
        self.setWindowTitle("Enheduanna IGI Companion")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.SubWindow
        )
        # Fully opaque solid window - NO transparent cuts or desktop bleed-through
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setMouseTracking(True)
        self.setMinimumSize(380, 480)
        self.setMaximumSize(1920, 1440)
        self.resize(self.config.hud.width, self.config.hud.height)
        self.setStyleSheet(QSS_STYLESHEET)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(1, 1, 1, 1)
        main_layout.setSpacing(0)

        # 1. Solid Header Bar (Draggable)
        self.header = QFrame()
        self.header.setObjectName("IgiHeader")
        h_layout = QHBoxLayout(self.header)
        h_layout.setContentsMargins(14, 10, 14, 10)

        # Status Dot
        self.status_dot = QLabel()
        self.status_dot.setObjectName("IgiStatusDot")
        self.status_dot.setFixedSize(8, 8)
        h_layout.addWidget(self.status_dot)

        # Title & Clean Subtitle
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        self.title_lbl = QLabel("IGI  𒅆  •  The Eye")
        self.title_lbl.setObjectName("IgiTitle")
        self.subtitle_lbl = QLabel("Enheduanna Visual Companion")
        self.subtitle_lbl.setObjectName("IgiSubtitle")
        title_box.addWidget(self.title_lbl)
        title_box.addWidget(self.subtitle_lbl)
        h_layout.addLayout(title_box)

        h_layout.addStretch()

        # Minimize Button
        self.min_btn = QPushButton("—")
        self.min_btn.setObjectName("IgiCloseBtn")
        self.min_btn.setToolTip("Minimize HUD")
        self.min_btn.clicked.connect(self.hide)
        h_layout.addWidget(self.min_btn)

        # Expand / Restore Button (Scalability toggle)
        self.expand_btn = QPushButton("⤢")
        self.expand_btn.setObjectName("IgiExpandBtn")
        self.expand_btn.setToolTip("Expand / Restore Window Size")
        self.expand_btn.clicked.connect(self._toggle_expand)
        h_layout.addWidget(self.expand_btn)

        # Close Button
        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("IgiCloseBtn")
        self.close_btn.setToolTip("Close HUD")
        self.close_btn.clicked.connect(self.hide)
        h_layout.addWidget(self.close_btn)

        main_layout.addWidget(self.header)

        # 2. Context Preview Card (Solid grey with crop thumbnail)
        self.context_card = ContextPreviewCard(self)
        main_layout.addWidget(self.context_card)

        # 3. Quick Action Pills (Solid grey)
        self.action_bar = QuickActionsBar(self)
        self.action_bar.action_triggered.connect(self.submit_prompt)
        main_layout.addWidget(self.action_bar)

        # 4. Solid Chat Transcript Area with Collapsible Evidence Drawer
        self.stream_view = ChatStreamView(self)
        main_layout.addWidget(self.stream_view, 1)

        # 5. Solid Input Bar with Corner SizeGrip
        self.input_container = QFrame()
        self.input_container.setObjectName("IgiInputContainer")
        in_layout = QHBoxLayout(self.input_container)
        in_layout.setContentsMargins(10, 8, 8, 8)
        in_layout.setSpacing(8)

        self.input_field = QLineEdit()
        self.input_field.setObjectName("IgiInputEdit")
        self.input_field.setPlaceholderText("Ask IGI about the circled section...")
        self.input_field.returnPressed.connect(self._on_input_submitted)
        in_layout.addWidget(self.input_field, 1)

        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("IgiSendBtn")
        self.send_btn.clicked.connect(self._on_input_submitted)
        in_layout.addWidget(self.send_btn)

        self.cancel_btn = QPushButton("✕ Cancel")
        self.cancel_btn.setObjectName("IgiCancelBtn")
        self.cancel_btn.setToolTip("Cancel active task")
        self.cancel_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: rgba(239, 68, 68, 0.15);"
            "  border: 1px solid #ef4444;"
            "  color: #f87171;"
            "  font-weight: bold;"
            "  border-radius: 4px;"
            "  padding: 4px 8px;"
            "}"
            "QPushButton:hover {"
            "  background-color: rgba(239, 68, 68, 0.30);"
            "}"
        )
        self.cancel_btn.clicked.connect(self.cancel_current_task)
        self.cancel_btn.hide()
        in_layout.addWidget(self.cancel_btn)

        # Native Bottom-Right Corner Resize Grip
        self.size_grip = QSizeGrip(self)
        self.size_grip.setToolTip("Drag to resize window")
        in_layout.addWidget(self.size_grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)

        main_layout.addWidget(self.input_container)

    def _connect_signals(self):
        self.signals.token_received.connect(self.stream_view.append_agent_token)
        self.signals.status_updated.connect(self._on_status_updated)
        self.signals.turn_finished.connect(self._on_turn_finished)
        self.signals.event_received.connect(self._on_orchestrator_event)
        self.signals.guidance_highlight_requested.connect(self._on_guidance_highlight_requested)
        self.signals.walkthrough_blocks_ready.connect(self._on_walkthrough_blocks_ready)
        self.signals.workflow_state_changed.connect(self._on_workflow_state_changed)
        self.signals.context_card_updated.connect(self._on_context_card_updated)

    def _on_context_card_updated(self, crop, display_chip: str, ocr_text: str, window_context: Any):
        """Thread-safe context card and metadata update."""
        self.context_card.set_content(crop, display_chip, ocr_text, window_context=window_context)
        self.current_crop = crop
        self.current_ocr_text = ocr_text
        if window_context and getattr(window_context, "title", None):
            self.current_window_title = window_context.title
            self.current_process_name = window_context.process_name
            self.current_window_context = window_context

    def _on_guidance_highlight_requested(self, bbox: list, label: str, description: str, duration_ms: int):
        if self.projector and bbox:
            self.projector.add_guidance_highlight(
                bbox=bbox,
                label=label,
                description=description,
                duration_ms=duration_ms
            )

    def _on_walkthrough_blocks_ready(self, blocks: list, duration_ms: int):
        if self.projector and blocks:
            self.projector.add_walkthrough_blocks(blocks, duration_ms=duration_ms)

    def _on_workflow_state_changed(self, new_state: str, subtitle_text: str):
        self._workflow_state = new_state
        if subtitle_text:
            self.subtitle_lbl.setText(subtitle_text[:40])

    def _toggle_expand(self):
        """Toggle between compact HUD mode and spacious expanded workstation mode."""
        screen = QGuiApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()

        if not self._is_expanded:
            self._normal_geo = self.geometry()
            target_w = min(740, int(geo.width() * 0.70))
            target_h = min(860, int(geo.height() * 0.88))
            x = geo.right() - target_w - self.config.hud.margin_right
            y = geo.bottom() - target_h - self.config.hud.margin_bottom
            self.setGeometry(x, y, target_w, target_h)
            self.expand_btn.setText("⤡")
            self._is_expanded = True
        else:
            if self._normal_geo:
                self.setGeometry(self._normal_geo)
            else:
                self.resize(self.config.hud.width, self.config.hud.height)
                self.position_bottom_right()
            self.expand_btn.setText("⤢")
            self._is_expanded = False

    def _on_orchestrator_event(self, evt_type: str, data: dict):
        if not isinstance(data, dict):
            return

        if evt_type == "tool_call_start":
            tool_name = data.get("name") or data.get("tool") or "tool"
            tool_id = data.get("id") or tool_name
            args = data.get("args") or {}
            self.stream_view.on_tool_call_start(tool_id, tool_name, args)
            self.subtitle_lbl.setText(f"Running {tool_name}...")

        elif evt_type == "tool_call_done":
            tool_name = data.get("name") or data.get("tool") or "tool"
            tool_id = data.get("id") or tool_name
            args = data.get("args") or {}
            dur = data.get("durationMs", 0)
            preview = data.get("resultPreview", "")
            is_err = data.get("isError", False)
            self.stream_view.on_tool_call_done(tool_id, tool_name, dur, preview, is_err, args)
            self.subtitle_lbl.setText(f"✓ {tool_name} completed ({dur}ms)")

            # If orchestrator called highlight_on_screen, project spatial highlight asynchronously off GUI thread
            if tool_name == "highlight_on_screen" and self.projector and self.sam_router:
                def async_highlight():
                    try:
                        from PIL import ImageGrab
                        screen = ImageGrab.grab()
                        target_q = args.get("target", "")
                        lbl = args.get("label", target_q.title())
                        desc = args.get("description", "")
                        _, r_hint = infer_concept_and_region(target_q)
                        matches = self.sam_router.ground_target(
                            screen, target_q, region_hint=r_hint, exclude_rect=self.geometry()
                        )
                        if matches:
                            if len(matches) > 1 and ("graph" in target_q.lower() or "block" in target_q.lower() or "all" in target_q.lower()):
                                walk_blocks = []
                                for idx, m in enumerate(matches[:4]):
                                    raw_t = m.get("concept", "")
                                    s_txt = m.get("source_text", raw_t)
                                    d_desc = self.core_client.quick_explain_block(s_txt)
                                    walk_blocks.append({
                                        "bbox": m.get("bbox"),
                                        "label": raw_t if len(raw_t) <= 32 else f"{lbl} {idx+1}",
                                        "description": d_desc or desc,
                                        "color_type": "cyan"
                                    })
                                self.signals.walkthrough_blocks_ready.emit(walk_blocks, 30000)
                            else:
                                bx = matches[0].get("bbox")
                                self.signals.guidance_highlight_requested.emit(
                                    bx,
                                    lbl,
                                    desc,
                                    15000
                                )
                    except Exception:
                        pass
                threading.Thread(target=async_highlight, daemon=True).start()

        elif evt_type == "tools_complete":
            count = data.get("callCount", 0)
            wall_ms = data.get("wallClockMs", 0)
            self.subtitle_lbl.setText(f"Synthesizing ({count} tools • {wall_ms}ms)")

        elif evt_type == "step_start":
            stage = "Synthesizing" if data.get("isSynthesis") else "Reasoning & Tools"
            step_num = data.get("step", 1)
            model_name = data.get("model", "")
            self.subtitle_lbl.setText(f"Step {step_num}: {stage}")
            self.stream_view.on_step_start(step_num, stage, model_name)

        elif evt_type == "step_narration":
            text = data.get("text", "")
            if text:
                self.stream_view.on_step_narration(text)
                self.subtitle_lbl.setText(text[:40])

        elif evt_type == "reasoning":
            self.subtitle_lbl.setText("🧠 Thinking...")

        elif evt_type == "approval_required":
            self.stream_view.show_approval_card(
                approval_data=data,
                on_decision=self.core_client.resolve_approval
            )
            self.subtitle_lbl.setText("Authorization required")

        elif evt_type == "approval_resolved":
            appr_id = data.get("id")
            dec = data.get("decision", "allow")
            self.stream_view.on_approval_resolved(appr_id, dec)
            self.subtitle_lbl.setText(f"✓ Authorization {dec}ed")

    def check_connection_status(self):
        """Check if localhost:4100 is healthy and update status pill."""
        health = self.core_client.check_health()
        if health.get("status") == "healthy":
            self.status_dot.setStyleSheet("background-color: #10b981; border-radius: 4px;")
            self.subtitle_lbl.setText("Connected to Localhost Core (Port 4100)")
        else:
            self.status_dot.setStyleSheet("background-color: #71717a; border-radius: 4px;")
            self.subtitle_lbl.setText("Core Offline • Direct API Ready")

    def position_bottom_right(self):
        """Align HUD window in the bottom-right corner of the active primary screen."""
        screen = QGuiApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        x = geo.right() - self.width() - self.config.hud.margin_right
        y = geo.bottom() - self.height() - self.config.hud.margin_bottom
        self.move(x, y)

    def set_selection_context(
        self,
        crop: Image.Image,
        ocr_text: str,
        window_title: str,
        process_name: str,
        window_context: Optional[Any] = None
    ):
        """Load newly segmented crop, active window context, and detected telemetry into the HUD."""
        self.current_crop = crop
        self.current_ocr_text = ocr_text
        self.current_window_title = window_title
        self.current_process_name = process_name
        self.current_window_context = window_context
        self._has_fresh_circle = True

        display_name = f"{process_name} — {window_title[:32]}..." if window_title else process_name
        self.context_card.set_content(crop, display_name, ocr_text, window_context=window_context)
        self.show()
        self.raise_()
        self.activateWindow()
        self.input_field.setFocus()

    def cancel_current_task(self):
        """Cancel current active visual reasoning / grounding task."""
        self._cancel_requested = True
        self.cancel_btn.hide()
        self.stream_view.stop_thinking_spinner()
        self.status_dot.setStyleSheet("background-color: #71717a; border-radius: 4px;")
        self.subtitle_lbl.setText("Task cancelled")

    def _on_input_submitted(self):
        text = self.input_field.text().strip()
        if text:
            self.input_field.clear()
            self.submit_prompt(text)

    def submit_prompt(self, prompt: str):
        """Submit user query and stream response with live screen segmentation."""
        if prompt == "__CLEAR_OVERLAY__":
            if self.projector:
                self.projector.clear_highlights()
            self._live_session_active = False
            self.subtitle_lbl.setText("Highlights cleared")
            return

        self._last_prompt = prompt
        self._cancel_requested = False
        self.cancel_btn.show()
        self.stream_view.add_user_message(prompt)
        self.stream_view.start_agent_response()
        self.status_dot.setStyleSheet("background-color: #3b82f6; border-radius: 4px;")  # Blue = Thinking

        final_crop = self.current_crop
        final_ocr = self.current_ocr_text
        final_title = self.current_window_title
        final_proc = self.current_process_name
        final_ctx = self.current_window_context
        has_circle = self._has_fresh_circle

        live_screenshot = None

        # 1. Fast Capture Guard: Grab screenshot without blocking GUI thread with synchronous OCR
        if not has_circle:
            try:
                from PIL import ImageGrab
                was_vis = False
                if self.projector and self.projector.isVisible():
                    was_vis = True
                    self.projector.hide()
                    QApplication.processEvents()

                live_screenshot = ImageGrab.grab()

                if was_vis and self.projector:
                    self.projector.show()

                final_crop = live_screenshot
                self.current_crop = live_screenshot
            except Exception:
                pass
        else:
            self._has_fresh_circle = False

        screen_to_analyze = live_screenshot or final_crop
        hud_geo = self.geometry()

        # Everything heavy (WinRT OCR, Window Context, SAM 3.1 Grounding, Core Chat Turn) runs in worker thread!
        def worker():
            try:
                nonlocal prompt, final_ocr, final_title, final_proc, final_ctx
                p_lower = prompt.lower()

                # Asynchronously extract OCR and active window telemetry in background
                if not has_circle and screen_to_analyze:
                    try:
                        from ..bridge.screen_context import get_active_window_context, extract_text_from_crop, enrich_window_context
                    except (ImportError, ValueError):
                        from bridge.screen_context import get_active_window_context, extract_text_from_crop, enrich_window_context

                    active_ctx = get_active_window_context()
                    final_ocr = extract_text_from_crop(screen_to_analyze)
                    if active_ctx and active_ctx.title and active_ctx.process_name != "Desktop":
                        final_title = active_ctx.title
                        final_proc = active_ctx.process_name
                        final_ctx = active_ctx
                        display_chip = active_ctx.display_chip
                        enrich_window_context(active_ctx, full_window_crop=screen_to_analyze)
                    else:
                        final_title = "Desktop Workspace"
                        final_proc = "Desktop"
                        final_ctx = active_ctx
                        display_chip = "Desktop Workspace"

                    self.signals.context_card_updated.emit(screen_to_analyze, display_chip, final_ocr, final_ctx)

                is_reply_workflow = any(k in p_lower for k in ("reply", "draft", "respond", "send email", "email", "mail")) and not any(k in p_lower for k in ("what is", "explain this code", "calc", "who is"))
                is_locate = any(k in p_lower for k in (
                    "where is", "where's", "find", "locate", "look for", "search for",
                    "cant find", "can't find", "identify", "button", "icon", "update", "tab", "graph",
                    "highlight", "segment", "segmentation", "point to", "spotlight", "show me",
                    "dollar", "credit", "balance", "$", "send"
                ))
                is_walkthrough = any(k in p_lower for k in (
                    "walkthrough", "walk through", "explain this code", "explain the code",
                    "code on screen", "live session", "interactive session", "explain each block",
                    "realtime", "real-time", "in real time", "understand these graphs", "understand this",
                    "live co-pilot", "live mode", "session mode", "mark all the graphs", "mark the graphs",
                    "mark all", "explain stuff right next to it", "highlight the graphs", "highlight graphs",
                    "highlight all graphs", "mark graphs", "show all graphs", "point out graphs"
                ))
                is_graph_walkthrough = any(g in p_lower for g in ("graph", "plot", "diagram", "figure", "curve"))
                screen_ctx_text = f"{final_title} {final_ocr} {getattr(final_ctx, 'detected_url', '')}".lower()
                is_graph_screen = is_graph_walkthrough or any(
                    g in screen_ctx_text for g in (
                        "graph", "plot", "diagram", "figure", "curve", "polynomial", "algebra",
                        "calculus", "parabola", "s-curve", "chart", "leading coefficient"
                    )
                )

                # 1. Email Reply Workflow via Hierarchical Grounding
                if is_reply_workflow and self.sam_router and screen_to_analyze:
                    try:
                        self.signals.status_updated.emit("Locating reply box (SAM 3.1)...")
                        reply_matches = self.sam_router.ground_target(
                            screen_to_analyze, "reply section", region_hint="bottom", exclude_rect=hud_geo
                        )
                        if not reply_matches or not reply_matches[0].get("is_optical_match"):
                            alt_matches = self.sam_router.ground_target(
                                screen_to_analyze, "reply", region_hint="bottom", exclude_rect=hud_geo
                            )
                            if alt_matches:
                                reply_matches = alt_matches

                        if reply_matches:
                            r_bbox = reply_matches[0].get("bbox")
                            spark_card = self.core_client.generate_spark_card_instruction(
                                target_name="Reply box",
                                task_context="User is replying to an email. Draft will be placed on clipboard; prompt user to paste Ctrl+V here."
                            ) or "Draft copied: Click here and press Ctrl+V to paste your reply."

                            # Emit signal to project highlight (persistent in live mode)
                            self.signals.guidance_highlight_requested.emit(r_bbox, "Reply Section", spark_card, 0)

                            sw, sh = screen_to_analyze.size
                            rx1 = max(0, min(sw - 1, r_bbox[0]))
                            ry1 = max(0, min(sh - 1, r_bbox[1]))
                            rx2 = max(rx1 + 1, min(sw, r_bbox[2]))
                            ry2 = max(ry1 + 1, min(sh, r_bbox[3]))
                            self._workflow_baseline_crop = screen_to_analyze.crop((rx1, ry1, rx2, ry2))
                            self._workflow_target_bbox = r_bbox
                            self.signals.workflow_state_changed.emit("AWAITING_REPLY_INPUT", "Reply box highlighted • Awaiting input")
                            QTimer.singleShot(0, self._workflow_timer.start)
                            prompt += f"\n\n[Visual Grounding]: The email reply section was identified at {r_bbox}."
                    except Exception:
                        pass

                # 2. Live Session / Walkthrough via Spark Spatial Planner -> Parallel SAM Grounding
                elif is_walkthrough and self.sam_router and screen_to_analyze:
                    try:
                        self.signals.status_updated.emit("🧠 Spark Brain: Planning spatial targets...")
                        detected_url = getattr(final_ctx, "detected_url", "") if hasattr(final_ctx, "detected_url") else ""
                        plan = self.core_client.spark_plan_targets(
                            screenshot=screen_to_analyze,
                            query=prompt,
                            window_title=final_title,
                            url=detected_url,
                            ocr_text=final_ocr
                        )
                        if self._cancel_requested:
                            return

                        targets = plan.get("targets", [])
                        intent = plan.get("intent", "explain_page")

                        # Determine badge/halo color by intent
                        if intent == "act":
                            default_color = "amber"
                        elif intent == "warn" or "alert" in intent:
                            default_color = "red"
                        else:
                            default_color = "cyan"

                        accumulated_blocks = []
                        from concurrent.futures import ThreadPoolExecutor, as_completed

                        def _ground_target_worker(idx_item):
                            idx, t = idx_item
                            t_concept = t.get("concept", "")
                            t_region = t.get("region_hint", "any")
                            t_ref = t.get("referring_expression", t_concept)
                            matches = self.sam_router.ground_target(
                                screenshot=screen_to_analyze,
                                target_concept=t_concept,
                                region_hint=t_region,
                                exclude_rect=hud_geo,
                                referring_expression=t_ref
                            )
                            if matches:
                                m = matches[0]
                                ctype = default_color
                                if t.get("color_type"):
                                    ctype = t.get("color_type")
                                return {
                                    "bbox": m.get("bbox"),
                                    "label": t.get("label", t_concept[:24]),
                                    "description": t.get("say", ""),
                                    "color_type": ctype,
                                    "index": idx + 1
                                }
                            return None

                        if targets:
                            num_workers = min(4, max(1, len(targets[:4])))
                            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                                futures = {
                                    executor.submit(_ground_target_worker, (idx, t)): idx
                                    for idx, t in enumerate(targets[:4])
                                }
                                for future in as_completed(futures):
                                    if self._cancel_requested:
                                        break
                                    try:
                                        block = future.result()
                                        if block:
                                            accumulated_blocks.append(block)
                                            # Maintain top-to-bottom reading order by index
                                            sorted_blocks = sorted(accumulated_blocks, key=lambda b: b.get("index", 0))
                                            # Emit progressively if projector enabled
                                            if self.projector:
                                                self.signals.walkthrough_blocks_ready.emit(list(sorted_blocks), 0)
                                            self.signals.status_updated.emit(f"👁️ Spatial Grounder: Located {len(sorted_blocks)}/{len(targets[:4])} regions...")
                                    except Exception:
                                        pass

                        # Fallback for graph screens or if planner returned 0 targets
                        if not accumulated_blocks:
                            if is_graph_screen:
                                matches = self.sam_router.ground_target(
                                    screen_to_analyze, "graph", region_hint="center", exclude_rect=hud_geo
                                )
                                for idx, m in enumerate(matches[:4]):
                                    raw_txt = m.get("concept", "")
                                    src_txt = m.get("source_text", raw_txt)
                                    desc = self.core_client.generate_spark_card_instruction(raw_txt, src_txt)
                                    lbl = raw_txt if len(raw_txt) <= 32 else f"Graph {idx+1}: {raw_txt[:26]}"
                                    accumulated_blocks.append({
                                        "bbox": m.get("bbox"),
                                        "label": lbl,
                                        "description": desc,
                                        "color_type": "cyan",
                                        "index": idx + 1
                                    })
                            if not accumulated_blocks:
                                segment_fn = getattr(self.sam_router, "segment_blocks", getattr(self.sam_router, "segment_code_or_ui_blocks", None))
                                if segment_fn:
                                    fallback_blocks = segment_fn(screen_to_analyze, allow_heuristic=False)
                                    for b in fallback_blocks:
                                        if not b.get("description"):
                                            b["description"] = self.core_client.generate_spark_card_instruction(
                                                b.get("label", "Element"),
                                                b.get("text", "")
                                            )
                                    accumulated_blocks = fallback_blocks

                            if accumulated_blocks and self.projector:
                                self.signals.walkthrough_blocks_ready.emit(accumulated_blocks, 0)

                        if accumulated_blocks:
                            self._live_session_active = True
                            self.signals.status_updated.emit(f"Walkthrough: {len(accumulated_blocks)} regions analyzed")
                            breakdown_text = "\n".join([f"{idx+1}. **{b.get('label')}**: {b.get('description')}" for idx, b in enumerate(accumulated_blocks)])
                            prompt += f"\n\n[Visual Grounding]: Screen walkthrough identified the following key regions:\n{breakdown_text}\nExplain each region clearly to the user in this chat response."
                    except Exception:
                        pass

                # 3. Targeted Locate / Spotlight with Grounded Vision (Spark Brain -> SAM Eyes -> Snap)
                elif is_locate and self.sam_router and screen_to_analyze:
                    try:
                        self.signals.status_updated.emit("🧠 Spark Brain: Analyzing visual context...")
                        spark_ground = self.core_client.spark_ground_concept(
                            screenshot=screen_to_analyze,
                            query=prompt,
                            window_title=final_title,
                            ocr_text=final_ocr
                        )
                        if self._cancel_requested:
                            return

                        target_concept = spark_ground.get("concept", "") or extract_concept_from_prompt(prompt)
                        r_hint = spark_ground.get("region_hint", "any")
                        ref_expr = spark_ground.get("referring_expression", "") or target_concept

                        self.signals.status_updated.emit(f"👁️ Spatial Grounder: Locating '{target_concept}' ({r_hint} region)...")
                        matches = self.sam_router.ground_target(
                            screenshot=screen_to_analyze,
                            target_concept=target_concept,
                            region_hint=r_hint,
                            exclude_rect=hud_geo,
                            referring_expression=ref_expr,
                            verify_with_brain=True,
                            core_client=self.core_client
                        )
                        if self._cancel_requested:
                            return

                        if matches and len(matches) > 0:
                            if "graph" in target_concept.lower() or len(matches) > 1:
                                blocks = []
                                for idx, item in enumerate(matches[:4]):
                                    ibx = item.get("bbox")
                                    raw_txt = item.get("concept", "")
                                    src_txt = item.get("source_text", raw_txt)
                                    desc = self.core_client.generate_spark_card_instruction(raw_txt, src_txt)
                                    lbl = raw_txt if len(raw_txt) <= 30 else f"Target {idx+1}: {raw_txt[:24]}"
                                    blocks.append({
                                        "bbox": ibx,
                                        "label": lbl,
                                        "description": desc,
                                        "color_type": "cyan"
                                    })
                                if self.projector:
                                    self.signals.walkthrough_blocks_ready.emit(blocks, 0 if self._live_session_active else 30000)
                                breakdown_text = "\n".join([f"{idx+1}. **{b.get('label')}**: {b.get('description')}" for idx, b in enumerate(blocks)])
                                prompt += f"\n\n[Visual Grounding]: Screen regions detected:\n{breakdown_text}"
                            else:
                                item = matches[0]
                                ibx = item.get("bbox")
                                desc = self.core_client.generate_spark_card_instruction(
                                    target_name=item.get("concept", target_concept),
                                    task_context=prompt
                                )
                                if self.projector:
                                    self.signals.guidance_highlight_requested.emit(
                                        ibx,
                                        f"IGI: {item.get('concept', target_concept).title()}",
                                        desc,
                                        0 if self._live_session_active else 20000
                                    )
                            best = matches[0]
                            prompt += f"\n\n[Visual Grounding]: The UI element '{best.get('concept', target_concept)}' was optically detected on the user's active screen at desktop coordinates {best.get('bbox')} (region: {r_hint})."
                    except Exception:
                        pass

                if self._cancel_requested:
                    return

                # 4. Stream chat turn
                def on_tok(tok):
                    self.signals.token_received.emit(tok)

                def on_stat(stat):
                    self.signals.status_updated.emit(stat)

                reply = self.core_client.stream_chat_turn(
                    prompt=prompt,
                    image_crop=final_crop,
                    ocr_text=final_ocr,
                    window_title=final_title,
                    process_name=final_proc,
                    window_context=final_ctx,
                    on_token=on_tok,
                    on_status=on_stat,
                    on_event=lambda evt, data: self.signals.event_received.emit(evt, data)
                )
                self.signals.turn_finished.emit(reply)
            except Exception as e:
                self.signals.turn_finished.emit(f"Error during live processing: {str(e)}")

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _on_status_updated(self, status: str):
        self.subtitle_lbl.setText(status[:38])

    def _on_turn_finished(self, full_text: str):
        self.cancel_btn.hide()
        self.stream_view.stop_thinking_spinner()
        self.status_dot.setStyleSheet("background-color: #10b981; border-radius: 4px;")
        self.subtitle_lbl.setText("Enheduanna Visual Companion")
        if not self.stream_view.current_agent_raw_text and full_text:
            self.stream_view.append_agent_token(full_text)

        # Proactive Next-Step Guidance: If user asked to draft an email or reply,
        # copy the clean generated draft text to clipboard and update subtitle
        p_low = (self._last_prompt or "").lower()
        if self._workflow_state == "AWAITING_REPLY_INPUT" or any(w in p_low for w in ("reply", "draft", "email", "respond")):
            if full_text:
                clean_body = full_text
                if "```" in clean_body:
                    parts = clean_body.split("```")
                    if len(parts) >= 3:
                        clean_body = parts[1].strip()
                        if clean_body.startswith("markdown") or clean_body.startswith("text"):
                            clean_body = clean_body.split("\n", 1)[-1].strip()
                try:
                    QApplication.clipboard().setText(clean_body)
                    self.subtitle_lbl.setText("✓ Draft copied to clipboard! Paste into reply section")
                except Exception:
                    pass

    def _on_workflow_tick(self):
        """
        Continuously evaluate live screen region for user visual actions asynchronously,
        driving the proactive self-loop of reasoning without blocking GUI thread.
        """
        if self._workflow_state == "IDLE" or not self._workflow_target_bbox or self._is_evaluating_tick:
            return

        self._is_evaluating_tick = True

        def tick_worker():
            try:
                from PIL import ImageGrab, ImageChops
                screen = ImageGrab.grab()
                bx1, by1, bx2, by2 = self._workflow_target_bbox
                sw, sh = screen.size
                cx1 = max(0, min(sw - 1, bx1))
                cy1 = max(0, min(sh - 1, by1))
                cx2 = max(cx1 + 1, min(sw, bx2))
                cy2 = max(cy1 + 1, min(sh, by2))

                curr_crop = screen.crop((cx1, cy1, cx2, cy2))

                if self._workflow_baseline_crop is None or self._workflow_baseline_crop.size != curr_crop.size:
                    self._workflow_baseline_crop = curr_crop
                    return

                diff = ImageChops.difference(self._workflow_baseline_crop, curr_crop)
                gray = diff.convert("L")
                p_data = getattr(gray, "get_flattened_data", gray.getdata)()
                changed_pixels = sum(1 for p in p_data if p > 25)

                if self._workflow_state == "AWAITING_REPLY_INPUT":
                    if changed_pixels > 60:
                        # Visual change detected! Text has entered the reply section
                        self.signals.workflow_state_changed.emit("AWAITING_SEND", "Text detected in reply! Locating Send button...")

                        send_matches = self.sam_router.route_concept(screen, "send button") if self.sam_router else []
                        if send_matches:
                            send_bbox = send_matches[0].get("bbox")
                        else:
                            send_bbox = [int(sw * 0.72), int(sh * 0.84), int(sw * 0.82), int(sh * 0.89)]

                        spark_instruction = self.core_client.generate_spark_card_instruction(
                            target_name="Send button",
                            task_context="Email draft has been entered in reply box. Guide user to click Send."
                        ) or "Click Send to dispatch your email."

                        self.signals.guidance_highlight_requested.emit(send_bbox, "Next Step: Send", spark_instruction, 0)
                        self._workflow_target_bbox = send_bbox
                        sx1 = max(0, min(sw - 1, send_bbox[0]))
                        sy1 = max(0, min(sh - 1, send_bbox[1]))
                        sx2 = max(sx1 + 1, min(sw, send_bbox[2]))
                        sy2 = max(sy1 + 1, min(sh, send_bbox[3]))
                        self._workflow_baseline_crop = screen.crop((sx1, sy1, sx2, sy2))

                elif self._workflow_state == "AWAITING_SEND":
                    if changed_pixels > 40:
                        self.signals.workflow_state_changed.emit("COMPLETED", "✓ Email sent! Guidance complete")
                        self.signals.guidance_highlight_requested.emit(
                            self._workflow_target_bbox,
                            "Done",
                            "Email sent successfully! Guidance workflow complete.",
                            3000
                        )
                        self._workflow_state = "IDLE"
                        self._workflow_target_bbox = None
                        self._workflow_baseline_crop = None
            except Exception:
                pass
            finally:
                self._is_evaluating_tick = False

        threading.Thread(target=tick_worker, daemon=True).start()

    def _start_live_heartbeat(self):
        """Mark live session active without disruptive autonomous screen spam."""
        self._live_session_active = True

    # -------------------------------------------------------------
    # Frameless Edge Resizing & Header Dragging Logic
    # -------------------------------------------------------------
    def _detect_edge(self, pos: QPoint) -> int:
        """Determine which border/corner edge the mouse is near."""
        edge = EDGE_NONE
        w = self.width()
        h = self.height()

        if pos.x() <= EDGE_MARGIN:
            edge |= EDGE_LEFT
        elif pos.x() >= w - EDGE_MARGIN:
            edge |= EDGE_RIGHT

        if pos.y() <= EDGE_MARGIN:
            edge |= EDGE_TOP
        elif pos.y() >= h - EDGE_MARGIN:
            edge |= EDGE_BOTTOM

        return edge

    def _update_cursor_for_edge(self, edge: int):
        """Set appropriate resize cursor based on hover edge."""
        if (edge == (EDGE_TOP | EDGE_LEFT)) or (edge == (EDGE_BOTTOM | EDGE_RIGHT)):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif (edge == (EDGE_TOP | EDGE_RIGHT)) or (edge == (EDGE_BOTTOM | EDGE_LEFT)):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif edge in (EDGE_LEFT, EDGE_RIGHT):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edge in (EDGE_TOP, EDGE_BOTTOM):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            edge = self._detect_edge(pos)

            if edge != EDGE_NONE:
                # Start border resize
                self._current_edge = edge
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_geo = self.geometry()
                event.accept()
                return

            # Check if clicked inside header for window dragging
            header_rect = self.header.geometry()
            if header_rect.contains(pos):
                self._is_dragging_header = True
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        global_pos = event.globalPosition().toPoint()
        pos = event.position().toPoint()

        # Handle active edge resize dragging
        if self._current_edge != EDGE_NONE:
            delta_x = global_pos.x() - self._resize_start_pos.x()
            delta_y = global_pos.y() - self._resize_start_pos.y()
            start = self._resize_start_geo

            new_x = start.x()
            new_y = start.y()
            new_w = start.width()
            new_h = start.height()

            if self._current_edge & EDGE_RIGHT:
                new_w = max(self.minimumWidth(), start.width() + delta_x)
            elif self._current_edge & EDGE_LEFT:
                w_candidate = start.width() - delta_x
                if w_candidate >= self.minimumWidth():
                    new_x = start.x() + delta_x
                    new_w = w_candidate

            if self._current_edge & EDGE_BOTTOM:
                new_h = max(self.minimumHeight(), start.height() + delta_y)
            elif self._current_edge & EDGE_TOP:
                h_candidate = start.height() - delta_y
                if h_candidate >= self.minimumHeight():
                    new_y = start.y() + delta_y
                    new_h = h_candidate

            self.setGeometry(new_x, new_y, new_w, new_h)
            event.accept()
            return

        # Handle active header dragging
        if self._is_dragging_header:
            self.move(global_pos - self._drag_pos)
            event.accept()
            return

        # Hovering: update cursor based on edge
        edge = self._detect_edge(pos)
        self._update_cursor_for_edge(edge)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._current_edge = EDGE_NONE
        self._is_dragging_header = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(event)
