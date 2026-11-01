"""
IGI (𒅆) — Streaming Conversation Transcript View & Markdown Renderer
Renders full GitHub-flavored Markdown (headers, bullet lists, bold, tables, code blocks)
and compact collapsible tool-execution drawer matching the localhost dashboard.
"""

from __future__ import annotations

import re
import html
from typing import Optional, Dict, Any, List, Callable

try:
    from PySide6.QtCore import Qt, QTimer, QRectF
    from PySide6.QtGui import QPainter, QPen, QColor, QFont, QPaintEvent, QCursor
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextBrowser, QScrollArea,
        QFrame, QSizePolicy, QPushButton
    )
except ImportError:
    pass


class ThinkingSpinner(QWidget):
    """Smooth rotating circular progress spinner for thinking state."""

    def __init__(self, size: int = 18, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.angle = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._rotate)
        self.is_spinning = False

    def start(self):
        self.is_spinning = True
        self.show()
        if not self.timer.isActive():
            self.timer.start(25)

    def stop(self):
        self.is_spinning = False
        self.timer.stop()
        self.hide()

    def _rotate(self):
        self.angle = (self.angle + 12) % 360
        self.update()

    def paintEvent(self, event: QPaintEvent):
        if not self.is_spinning:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(2, 2, self.width() - 4, self.height() - 4)

        # Background track
        pen_track = QPen(QColor(50, 53, 64), 2)
        painter.setPen(pen_track)
        painter.drawEllipse(rect)

        # Active spinning arc
        pen_arc = QPen(QColor(245, 158, 11), 2.2)  # Amber / Gold
        pen_arc.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen_arc)
        painter.drawArc(rect, -int(self.angle * 16), 110 * 16)


class ToolItemRow(QFrame):
    """Row displaying detailed tool name, duration badge, arguments, and result preview."""

    def __init__(self, tool_id: str, name: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.tool_id = tool_id
        self.name = name
        self.setProperty("class", "ToolItemRow")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(3)

        # Header row
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        self.icon_lbl = QLabel("⚡")
        self.icon_lbl.setStyleSheet("font-size: 11px; color: #f59e0b;")
        header.addWidget(self.icon_lbl)

        self.name_lbl = QLabel(name)
        self.name_lbl.setProperty("class", "ToolNameLabel")
        self.name_lbl.setStyleSheet("font-family: Consolas, monospace; font-size: 11px; font-weight: 600; color: #38bdf8;")
        header.addWidget(self.name_lbl)

        header.addStretch()

        self.dur_lbl = QLabel("running...")
        self.dur_lbl.setProperty("class", "ToolDurationBadge")
        self.dur_lbl.setStyleSheet("font-family: Consolas, monospace; font-size: 10px; color: #f59e0b; background-color: #121318; border: 1px solid #252833; border-radius: 3px; padding: 1px 5px;")
        header.addWidget(self.dur_lbl)

        layout.addLayout(header)

        # Details preview (args / result preview)
        self.detail_lbl = QLabel()
        self.detail_lbl.setProperty("class", "ToolDetailText")
        self.detail_lbl.setWordWrap(True)
        self.detail_lbl.setStyleSheet("font-family: Consolas, monospace; font-size: 10px; color: #a1a1aa; background-color: #131418; border-radius: 4px; padding: 3px 6px;")
        self.detail_lbl.hide()
        layout.addWidget(self.detail_lbl)

    def set_running(self, name: str, args: Optional[dict] = None):
        self.name = name
        self.name_lbl.setText(name)
        self.icon_lbl.setText("⚡")
        self.icon_lbl.setStyleSheet("font-size: 11px; color: #f59e0b;")
        self.dur_lbl.setText("running...")
        self.dur_lbl.setStyleSheet("font-family: Consolas, monospace; font-size: 10px; color: #f59e0b; background-color: #121318; border: 1px solid #252833; border-radius: 3px; padding: 1px 5px;")

        if args and isinstance(args, dict):
            args_str = ", ".join(f"{k}={repr(v)[:32]}" for k, v in args.items() if k != "sessionId")
            if args_str:
                self.detail_lbl.setText(f"args: ({args_str})")
                self.detail_lbl.show()

    def set_done(
        self,
        name: str,
        duration_ms: int = 0,
        preview: str = "",
        is_error: bool = False,
        args: Optional[dict] = None
    ):
        self.name = name
        self.name_lbl.setText(name)
        if is_error:
            self.icon_lbl.setText("✕")
            self.icon_lbl.setStyleSheet("font-size: 11px; color: #ef4444;")
            self.dur_lbl.setText("failed")
            self.dur_lbl.setStyleSheet("font-family: Consolas, monospace; font-size: 10px; color: #ef4444; background-color: #121318; border: 1px solid #331515; border-radius: 3px; padding: 1px 5px;")
        else:
            self.icon_lbl.setText("✓")
            self.icon_lbl.setStyleSheet("font-size: 11px; color: #10b981;")
            self.dur_lbl.setText(f"{duration_ms}ms" if duration_ms > 0 else "done")
            self.dur_lbl.setStyleSheet("font-family: Consolas, monospace; font-size: 10px; color: #10b981; background-color: #121318; border: 1px solid #1c2b22; border-radius: 3px; padding: 1px 5px;")

        details = []
        if args and isinstance(args, dict):
            args_str = ", ".join(f"{k}={repr(v)[:32]}" for k, v in args.items() if k != "sessionId")
            if args_str:
                details.append(f"args: ({args_str})")
        if preview and preview.strip():
            clean_prev = preview.strip().replace("\r\n", " ").replace("\n", " ")
            if len(clean_prev) > 130:
                clean_prev = clean_prev[:127] + "..."
            details.append(f"result: {clean_prev}")

        if details:
            self.detail_lbl.setText("\n".join(details))
            self.detail_lbl.show()
        else:
            self.detail_lbl.hide()


class ToolCallsDrawer(QFrame):
    """Collapsible evidence drawer matching the localhost dashboard."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("IgiToolDrawer")
        self.tool_items: Dict[str, ToolItemRow] = {}
        self.call_order: List[str] = []
        self.total_duration_ms: int = 0
        self.is_expanded_state: bool = True

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header Toggle Button
        self.header_btn = QPushButton(self)
        self.header_btn.setObjectName("IgiDrawerHeader")
        self.header_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header_btn.clicked.connect(self.toggle_expanded)

        h_layout = QHBoxLayout(self.header_btn)
        h_layout.setContentsMargins(8, 5, 8, 5)
        h_layout.setSpacing(6)

        self.summary_icon = QLabel("⚡")
        self.summary_icon.setStyleSheet("font-size: 11px; color: #f59e0b;")
        h_layout.addWidget(self.summary_icon)

        self.summary_text = QLabel("Tools & Evidence (0 calls)")
        self.summary_text.setStyleSheet("font-size: 11px; font-weight: 600; color: #d4d4d8;")
        h_layout.addWidget(self.summary_text)

        h_layout.addStretch()

        self.chevron = QLabel("▾")
        self.chevron.setStyleSheet("font-size: 11px; color: #71717a;")
        h_layout.addWidget(self.chevron)

        main_layout.addWidget(self.header_btn)

        # Body Container
        self.body = QFrame(self)
        self.body.setObjectName("IgiDrawerBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(6, 6, 6, 6)
        self.body_layout.setSpacing(4)
        main_layout.addWidget(self.body)

    def toggle_expanded(self):
        self.set_expanded(not self.is_expanded_state)

    def set_expanded(self, expanded: bool):
        self.is_expanded_state = expanded
        self.body.setVisible(expanded)
        self.chevron.setText("▾" if expanded else "▸")

    def is_expanded(self) -> bool:
        return self.is_expanded_state

    def record_tool_start(self, tool_id: str, name: str, args: Optional[dict] = None):
        key = tool_id or f"tool_{len(self.tool_items)}"
        if key not in self.tool_items:
            item = ToolItemRow(key, name, parent=self.body)
            self.tool_items[key] = item
            self.call_order.append(key)
            self.body_layout.addWidget(item)
        else:
            item = self.tool_items[key]

        item.set_running(name, args)

        # Update header summary
        self.summary_icon.setText("⚡")
        self.summary_icon.setStyleSheet("font-size: 11px; color: #f59e0b;")
        self.summary_text.setText(f"Executing {name}... ({len(self.tool_items)} calls)")

    def record_tool_done(
        self,
        tool_id: str,
        name: str,
        duration_ms: int = 0,
        result_preview: str = "",
        is_error: bool = False,
        args: Optional[dict] = None
    ):
        key = tool_id or name
        if key not in self.tool_items:
            item = ToolItemRow(key, name, parent=self.body)
            self.tool_items[key] = item
            self.call_order.append(key)
            self.body_layout.addWidget(item)
        else:
            item = self.tool_items[key]

        item.set_done(name, duration_ms, result_preview, is_error, args)
        if duration_ms > 0:
            self.total_duration_ms += duration_ms

        count = len(self.tool_items)
        pl = "call" if count == 1 else "calls"
        dur_str = f" • {self.total_duration_ms}ms" if self.total_duration_ms > 0 else ""

        self.summary_icon.setText("✓" if not is_error else "✕")
        self.summary_icon.setStyleSheet("font-size: 11px; color: #10b981;" if not is_error else "color: #ef4444;")
        self.summary_text.setText(f"Tools & Evidence ({count} {pl}{dur_str})")


class ApprovalCardWidget(QFrame):
    """Interactive Authorization Dialog Card for policy/tool approvals (Allow/Deny)."""

    def __init__(
        self,
        approval_data: dict,
        on_decision: Optional[Callable[[str, str], bool]] = None,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self.setObjectName("IgiApprovalCard")
        self.approval_data = approval_data
        self.on_decision = on_decision
        self.approval_id = approval_data.get("id", "")
        self.tool_name = approval_data.get("toolName", "tool")
        self.is_resolved = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # 1. Header row
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(6)

        icon = QLabel("⚠️")
        icon.setStyleSheet("font-size: 13px; color: #f59e0b;")
        header_row.addWidget(icon)

        title_text = approval_data.get("title") or f"Authorize {self.tool_name}"
        self.title_lbl = QLabel(title_text)
        self.title_lbl.setObjectName("IgiApprovalTitle")
        self.title_lbl.setStyleSheet("font-size: 12px; font-weight: 700; color: #f59e0b;")
        header_row.addWidget(self.title_lbl)

        header_row.addStretch()

        tool_chip = QLabel(self.tool_name)
        tool_chip.setStyleSheet("font-family: Consolas, monospace; font-size: 10px; color: #38bdf8; background-color: #121318; border: 1px solid #252833; border-radius: 3px; padding: 1px 5px;")
        header_row.addWidget(tool_chip)

        layout.addLayout(header_row)

        # 2. Description
        desc_text = approval_data.get("description") or f"Enheduanna is requesting permission to execute {self.tool_name}."
        self.desc_lbl = QLabel(desc_text)
        self.desc_lbl.setObjectName("IgiApprovalDesc")
        self.desc_lbl.setWordWrap(True)
        self.desc_lbl.setStyleSheet("font-size: 11px; color: #e4e4e7; line-height: 1.4;")
        layout.addWidget(self.desc_lbl)

        # 3. Formatted Arguments Box
        args = approval_data.get("args") or {}
        if args and isinstance(args, dict):
            clean_args = {k: v for k, v in args.items() if k != "sessionId"}
            if clean_args:
                args_lines = [f"{k}: {v}" for k, v in clean_args.items()]
                self.args_lbl = QLabel("\n".join(args_lines))
                self.args_lbl.setObjectName("IgiApprovalArgs")
                self.args_lbl.setWordWrap(True)
                self.args_lbl.setStyleSheet("font-family: Consolas, monospace; font-size: 10px; color: #38bdf8; background-color: #141416; border: 1px solid #2b2b34; border-radius: 4px; padding: 4px 8px;")
                layout.addWidget(self.args_lbl)

        # 4. Action Buttons row
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 4, 0, 0)
        btn_row.setSpacing(8)

        self.allow_btn = QPushButton("✓ Allow")
        self.allow_btn.setObjectName("IgiAllowBtn")
        self.allow_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.allow_btn.setStyleSheet("background-color: #059669; color: #ffffff; font-weight: 600; font-size: 11px; border: none; border-radius: 5px; padding: 6px 14px;")
        self.allow_btn.clicked.connect(self._on_allow_clicked)
        btn_row.addWidget(self.allow_btn)

        self.deny_btn = QPushButton("✕ Deny")
        self.deny_btn.setObjectName("IgiDenyBtn")
        self.deny_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.deny_btn.setStyleSheet("background-color: #dc2626; color: #ffffff; font-weight: 600; font-size: 11px; border: none; border-radius: 5px; padding: 6px 14px;")
        self.deny_btn.clicked.connect(self._on_deny_clicked)
        btn_row.addWidget(self.deny_btn)

        self.status_lbl = QLabel()
        self.status_lbl.setObjectName("IgiApprovalStatus")
        self.status_lbl.hide()
        btn_row.addWidget(self.status_lbl)

        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _on_allow_clicked(self):
        if self.is_resolved:
            return
        self.is_resolved = True
        self.allow_btn.setEnabled(False)
        self.deny_btn.setEnabled(False)
        self.status_lbl.setText("✓ Allowed (Policy Granted)")
        self.status_lbl.setStyleSheet("color: #10b981; font-weight: 600; font-size: 11px; background-color: #102e1c; border: 1px solid #10b981; border-radius: 4px; padding: 3px 8px;")
        self.status_lbl.show()
        if self.on_decision:
            try:
                self.on_decision(self.approval_id, "allow")
            except Exception:
                pass

    def _on_deny_clicked(self):
        if self.is_resolved:
            return
        self.is_resolved = True
        self.allow_btn.setEnabled(False)
        self.deny_btn.setEnabled(False)
        self.status_lbl.setText("✕ Denied (Execution Cancelled)")
        self.status_lbl.setStyleSheet("color: #ef4444; font-weight: 600; font-size: 11px; background-color: #331515; border: 1px solid #ef4444; border-radius: 4px; padding: 3px 8px;")
        self.status_lbl.show()
        if self.on_decision:
            try:
                self.on_decision(self.approval_id, "deny")
            except Exception:
                pass

    def set_external_resolution(self, decision: str):
        """Update UI if resolved externally via web dashboard."""
        if self.is_resolved:
            return
        self.is_resolved = True
        self.allow_btn.setEnabled(False)
        self.deny_btn.setEnabled(False)
        if decision == "allow":
            self.status_lbl.setText("✓ Allowed")
            self.status_lbl.setStyleSheet("color: #10b981; font-weight: 600; font-size: 11px; background-color: #102e1c; border: 1px solid #10b981; border-radius: 4px; padding: 3px 8px;")
        else:
            self.status_lbl.setText("✕ Denied")
            self.status_lbl.setStyleSheet("color: #ef4444; font-weight: 600; font-size: 11px; background-color: #331515; border: 1px solid #ef4444; border-radius: 4px; padding: 3px 8px;")
        self.status_lbl.show()


def format_markdown_to_html(raw_md: str) -> str:
    """Robust Markdown to styled HTML converter."""
    lines = raw_md.split("\n")
    processed_lines = []
    in_code_block = False
    code_block_lines = []
    code_lang = ""

    for line in lines:
        stripped = line.strip()

        # Handle code blocks ```
        if stripped.startswith("```"):
            if not in_code_block:
                in_code_block = True
                code_lang = stripped[3:].strip()
                code_block_lines = []
            else:
                in_code_block = False
                code_text = html.escape("\n".join(code_block_lines))
                lang_badge = f'<div style="font-size: 9px; color: #71717a; text-transform: uppercase; margin-bottom: 4px;">{code_lang}</div>' if code_lang else ""
                processed_lines.append(
                    f'<div style="background-color: #14151a; border: 1px solid #282a33; '
                    f'border-radius: 6px; padding: 8px 10px; margin: 8px 0; font-family: Consolas, monospace; '
                    f'font-size: 11px; color: #38bdf8; white-space: pre-wrap;">{lang_badge}{code_text}</div>'
                )
            continue

        if in_code_block:
            code_block_lines.append(line)
            continue

        # Handle headers
        if stripped.startswith("### "):
            header_text = html.escape(stripped[4:])
            processed_lines.append(
                f'<h4 style="color: #f4f4f5; font-size: 12px; font-weight: 600; margin: 10px 0 4px 0;">{header_text}</h4>'
            )
            continue
        elif stripped.startswith("## "):
            header_text = html.escape(stripped[3:])
            processed_lines.append(
                f'<h3 style="color: #ffffff; font-size: 13px; font-weight: 700; margin: 12px 0 5px 0;">{header_text}</h3>'
            )
            continue
        elif stripped.startswith("# "):
            header_text = html.escape(stripped[2:])
            processed_lines.append(
                f'<h2 style="color: #ffffff; font-size: 14px; font-weight: 700; margin: 14px 0 6px 0; border-bottom: 1px solid #2e303b; padding-bottom: 4px;">{header_text}</h2>'
            )
            continue

        # Handle horizontal divider
        if stripped in ("---", "***", "___"):
            processed_lines.append('<hr style="border: none; border-top: 1px solid #2f323c; margin: 8px 0;">')
            continue

        # Handle bullet points (* or -)
        if stripped.startswith("* ") or stripped.startswith("- "):
            item_text = html.escape(stripped[2:])
            item_text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', item_text)
            item_text = re.sub(
                r'`([^`]+)`',
                r'<code style="background-color: #1e1f26; color: #fbbf24; padding: 1px 4px; border-radius: 3px; font-family: Consolas, monospace;">\1</code>',
                item_text
            )
            processed_lines.append(
                f'<div style="margin: 3px 0 3px 12px; line-height: 1.4;">'
                f'<span style="color: #a1a1aa; margin-right: 6px;">•</span>{item_text}</div>'
            )
            continue

        # Regular paragraph
        if stripped:
            text = html.escape(line)
            text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)
            text = re.sub(r'\*([^*]+)\*', r'<i>\1</i>', text)
            text = re.sub(
                r'`([^`]+)`',
                r'<code style="background-color: #1e1f26; color: #fbbf24; padding: 1px 4px; border-radius: 3px; font-family: Consolas, monospace;">\1</code>',
                text
            )
            processed_lines.append(f'<p style="margin: 4px 0; line-height: 1.45;">{text}</p>')
        else:
            processed_lines.append('<div style="height: 4px;"></div>')

    if in_code_block:
        code_text = html.escape("\n".join(code_block_lines))
        processed_lines.append(
            f'<div style="background-color: #14151a; border: 1px solid #282a33; border-radius: 6px; padding: 8px 10px; font-family: Consolas, monospace; font-size: 11px; color: #38bdf8; white-space: pre-wrap;">{code_text}</div>'
        )

    return "".join(processed_lines)


class ChatStreamView(QScrollArea):
    """Scrollable transcript view with rich markdown formatting and collapsible tool drawer."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.container = QWidget()
        self.container.setObjectName("IgiChatTranscript")
        self.layout = QVBoxLayout(self.container)
        self.layout.setContentsMargins(12, 10, 12, 10)
        self.layout.setSpacing(10)
        self.layout.addStretch()

        self.setWidget(self.container)
        self.current_agent_browser: Optional[QTextBrowser] = None
        self.current_agent_raw_text: str = ""
        self.current_spinner: Optional[ThinkingSpinner] = None
        self.current_agent_bubble: Optional[QFrame] = None
        self.current_drawer: Optional[ToolCallsDrawer] = None
        self.approval_cards: Dict[str, ApprovalCardWidget] = {}

    def add_user_message(self, text: str):
        """Append a solid user message bubble."""
        bubble = QFrame()
        bubble.setProperty("class", "UserBubble")
        b_layout = QVBoxLayout(bubble)
        b_layout.setContentsMargins(12, 8, 12, 8)

        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: #ffffff; font-size: 12px;")
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        b_layout.addWidget(lbl)

        self.layout.insertWidget(self.layout.count() - 1, bubble)
        self.scroll_to_bottom()

    def start_agent_response(self) -> QTextBrowser:
        """Create a new solid streaming agent bubble with rotating spinner."""
        bubble = QFrame()
        bubble.setProperty("class", "AgentBubble")
        b_layout = QVBoxLayout(bubble)
        b_layout.setContentsMargins(12, 10, 12, 10)
        self.current_agent_bubble = bubble
        self.current_drawer = None

        # Header row: Agent name + Rotating thinking spinner
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 4)
        header_row.setSpacing(8)

        header = QLabel("IGI (𒅆) • Wonder 1.0")
        header.setStyleSheet("color: #a1a1aa; font-size: 11px; font-weight: 600;")
        header_row.addWidget(header)

        # Spinning thinking indicator
        self.current_spinner = ThinkingSpinner(size=14, parent=bubble)
        self.current_spinner.start()
        header_row.addWidget(self.current_spinner)

        # Live Backend Activity Badge
        self.current_status_badge = QLabel("Thinking...")
        self.current_status_badge.setStyleSheet("color: #f59e0b; font-size: 11px; font-family: Consolas, monospace;")
        header_row.addWidget(self.current_status_badge)

        header_row.addStretch()
        b_layout.addLayout(header_row)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setStyleSheet("background: transparent; border: none; font-size: 12px; color: #f4f4f5;")
        browser.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        b_layout.addWidget(browser)

        self.current_agent_browser = browser
        self.current_agent_raw_text = ""

        self.layout.insertWidget(self.layout.count() - 1, bubble)
        self.scroll_to_bottom()
        return browser

    def _ensure_drawer(self) -> ToolCallsDrawer:
        """Ensure a collapsible tool drawer exists inside the current agent bubble."""
        if not self.current_agent_bubble:
            self.start_agent_response()

        if not self.current_drawer and self.current_agent_bubble:
            drawer = ToolCallsDrawer(parent=self.current_agent_bubble)
            bubble_layout = self.current_agent_bubble.layout()
            if bubble_layout:
                # Insert directly above QTextBrowser
                bubble_layout.insertWidget(bubble_layout.count() - 1, drawer)
            self.current_drawer = drawer
        return self.current_drawer

    def on_step_start(self, step: int, stage: str, model: str = ""):
        """Update live status badge for active step and stage."""
        if hasattr(self, "current_status_badge") and self.current_status_badge:
            self.current_status_badge.setText(f"Step {step}: {stage}...")
            self.current_status_badge.setStyleSheet("color: #f59e0b; font-size: 11px; font-family: Consolas, monospace;")
            self.current_status_badge.show()

    def on_step_narration(self, text: str):
        """Update live status badge with intermediate model reasoning or progress."""
        if hasattr(self, "current_status_badge") and self.current_status_badge:
            clean = text.strip().replace("\n", " ")
            if len(clean) > 45:
                clean = clean[:42] + "..."
            self.current_status_badge.setText(clean)
            self.current_status_badge.setStyleSheet("color: #a1a1aa; font-size: 10px; font-family: Consolas, monospace;")
            self.current_status_badge.show()

    def on_tool_call_start(self, tool_id: str, name: str, args: Optional[dict] = None):
        """Record start of a specific tool execution with real name and arguments."""
        if hasattr(self, "current_status_badge") and self.current_status_badge:
            self.current_status_badge.setText(f"⚡ {name}...")
            self.current_status_badge.setStyleSheet("color: #38bdf8; font-size: 11px; font-family: Consolas, monospace;")
            self.current_status_badge.show()

        drawer = self._ensure_drawer()
        if drawer:
            drawer.record_tool_start(tool_id, name, args)
            self.scroll_to_bottom()

    def on_tool_call_done(
        self,
        tool_id: str,
        name: str,
        duration_ms: int = 0,
        result_preview: str = "",
        is_error: bool = False,
        args: Optional[dict] = None
    ):
        """Record completion of a specific tool execution with duration and preview."""
        if hasattr(self, "current_status_badge") and self.current_status_badge:
            dur_str = f" ({duration_ms}ms)" if duration_ms > 0 else ""
            if is_error:
                self.current_status_badge.setText(f"✕ {name} failed")
                self.current_status_badge.setStyleSheet("color: #ef4444; font-size: 11px; font-family: Consolas, monospace;")
            else:
                self.current_status_badge.setText(f"✓ {name}{dur_str}")
                self.current_status_badge.setStyleSheet("color: #10b981; font-size: 11px; font-family: Consolas, monospace;")
            self.current_status_badge.show()

        drawer = self._ensure_drawer()
        if drawer:
            drawer.record_tool_done(tool_id, name, duration_ms, result_preview, is_error, args)
            self.scroll_to_bottom()

    def add_tool_call_badge(self, tool_name: str, status: str = "running", duration_ms: int = 0):
        """Backward-compatible method mapping into the drawer."""
        if status == "running":
            self.on_tool_call_start(tool_name, tool_name, None)
        else:
            self.on_tool_call_done(tool_name, tool_name, duration_ms)

    def show_approval_card(self, approval_data: dict, on_decision: Optional[Callable[[str, str], bool]] = None):
        """Display interactive Allow/Deny dialog card inside active agent bubble or transcript."""
        appr_id = approval_data.get("id") or f"appr_{len(self.approval_cards)}"
        card = ApprovalCardWidget(approval_data, on_decision=on_decision, parent=self.container)
        self.approval_cards[appr_id] = card

        if self.current_agent_bubble and self.current_agent_bubble.layout():
            b_layout = self.current_agent_bubble.layout()
            # Insert above the markdown response browser
            b_layout.insertWidget(max(0, b_layout.count() - 1), card)
        else:
            self.layout.insertWidget(max(0, self.layout.count() - 1), card)

        self.scroll_to_bottom()

    def on_approval_resolved(self, approval_id: str, decision: str):
        """Update card state when an approval is resolved."""
        if approval_id and approval_id in self.approval_cards:
            self.approval_cards[approval_id].set_external_resolution(decision)

    def stop_thinking_spinner(self):
        """Stop and hide the spinner when synthesis is complete."""
        if self.current_spinner:
            self.current_spinner.stop()
        if hasattr(self, "current_status_badge") and self.current_status_badge:
            self.current_status_badge.hide()

    def append_agent_token(self, token: str):
        """Append incoming delta token to active agent bubble and update rich markdown."""
        if not self.current_agent_browser:
            self.start_agent_response()

        # If tools were executed and the drawer is still open, collapse it on the first token stream
        # so the user can immediately read the response without scrolling past a wall of tools!
        if self.current_drawer and self.current_drawer.is_expanded():
            self.current_drawer.set_expanded(False)

        self.current_agent_raw_text += token
        formatted = format_markdown_to_html(self.current_agent_raw_text)
        self.current_agent_browser.setHtml(formatted)

        # Dynamic height expansion
        doc_height = int(self.current_agent_browser.document().size().height()) + 20
        self.current_agent_browser.setMinimumHeight(min(max(doc_height, 40), 600))

        self.scroll_to_bottom()

    def scroll_to_bottom(self):
        """Scroll transcript smoothly to bottom."""
        QTimer.singleShot(15, lambda: self.verticalScrollBar().setValue(self.verticalScrollBar().maximum()))
