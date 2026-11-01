"""
IGI (𒅆) — Sleek Professional Dark Grey Visual Theme
Clean, unified, solid dark-grey aesthetic with zero transparent gaps.
"""

from __future__ import annotations

# Solid Professional Grey Palette
BG_WINDOW = "#1c1d22"
BG_HEADER = "#22242b"
BG_SURFACE = "#252730"
BG_CARD = "#262832"
BG_CARD_HOVER = "#2f313d"
BG_INPUT = "#18191d"

BORDER_MUTED = "#30323c"
BORDER_HIGHLIGHT = "#454856"

TEXT_PRIMARY = "#f3f4f6"
TEXT_SECONDARY = "#a1a1aa"
TEXT_MUTED = "#71717a"

USER_BUBBLE_BG = "#2a2d38"
USER_BUBBLE_BORDER = "#383c4a"

AGENT_BUBBLE_BG = "#22242c"
AGENT_BUBBLE_BORDER = "#2f323c"

PILL_BG = "#262831"
PILL_BORDER = "#353844"
PILL_HOVER = "#363945"

ACCENT_BLUE = "#3b82f6"
SUCCESS_GREEN = "#10b981"
WARNING_RED = "#ef4444"


QSS_STYLESHEET = f"""
/* Global Reset */
QWidget {{
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    color: {TEXT_PRIMARY};
}}

/* Main Floating Window Frame - 100% Solid Dark Grey Container */
#IgiHudWindow {{
    background-color: {BG_WINDOW};
    border: 1px solid {BORDER_MUTED};
    border-radius: 12px;
}}

/* Header Bar */
#IgiHeader {{
    background-color: {BG_HEADER};
    border-top-left-radius: 11px;
    border-top-right-radius: 11px;
    border-bottom: 1px solid {BORDER_MUTED};
    padding: 10px 14px;
}}

#IgiTitle {{
    font-size: 13px;
    font-weight: 600;
    color: {TEXT_PRIMARY};
    letter-spacing: 0.3px;
}}

#IgiSubtitle {{
    font-size: 11px;
    color: {TEXT_MUTED};
}}

#IgiStatusDot {{
    border-radius: 4px;
    background-color: {SUCCESS_GREEN};
}}

/* Window Controls */
#IgiCloseBtn, #IgiExpandBtn {{
    background: transparent;
    color: {TEXT_SECONDARY};
    border: none;
    font-size: 13px;
    font-weight: bold;
    padding: 3px 8px;
    border-radius: 4px;
}}
#IgiCloseBtn:hover, #IgiExpandBtn:hover {{
    background-color: #2e303b;
    color: {TEXT_PRIMARY};
}}

/* Integrated Context Preview Bar */
#IgiContextCard {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER_MUTED};
    border-radius: 8px;
    padding: 8px 10px;
    margin: 8px 12px 4px 12px;
}}

#IgiAppBadge {{
    font-size: 11px;
    font-weight: 600;
    color: #e4e4e7;
    background-color: #1e1f26;
    border: 1px solid {BORDER_MUTED};
    border-radius: 4px;
    padding: 2px 6px;
}}

#IgiOcrSnippet {{
    font-family: 'Consolas', 'Fira Code', monospace;
    font-size: 11px;
    color: {TEXT_SECONDARY};
    background-color: {BG_INPUT};
    border-radius: 4px;
    padding: 4px 8px;
    border: 1px solid #23252d;
}}

/* Action Pills */
QPushButton.IgiPill {{
    background-color: {PILL_BG};
    color: #d4d4d8;
    border: 1px solid {PILL_BORDER};
    border-radius: 6px;
    padding: 5px 11px;
    font-size: 11px;
    font-weight: 500;
}}
QPushButton.IgiPill:hover {{
    background-color: {PILL_HOVER};
    border: 1px solid {BORDER_HIGHLIGHT};
    color: #ffffff;
}}

/* Chat Scroll Area & Container */
QScrollArea {{
    background-color: {BG_WINDOW};
    border: none;
}}

#IgiChatTranscript {{
    background-color: {BG_WINDOW};
    padding: 6px 12px;
}}

/* User Sent Message Bubble - Fully Opaque Solid Dark Grey */
.UserBubble {{
    background-color: {USER_BUBBLE_BG};
    border: 1px solid {USER_BUBBLE_BORDER};
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 12px;
    color: #ffffff;
}}

/* Agent Message Bubble - Fully Opaque Solid Surface */
.AgentBubble {{
    background-color: {AGENT_BUBBLE_BG};
    border: 1px solid {AGENT_BUBBLE_BORDER};
    border-radius: 8px;
    padding: 10px 12px;
    font-size: 12px;
    line-height: 1.45;
    color: #e4e4e7;
}}

/* Collapsible Evidence & Tool Calls Drawer */
#IgiToolDrawer {{
    background-color: #1a1b22;
    border: 1px solid #2d303c;
    border-radius: 6px;
    margin: 4px 0 6px 0;
}}

#IgiDrawerHeader {{
    background-color: #21232c;
    border: none;
    border-radius: 5px;
    padding: 5px 8px;
    text-align: left;
    color: #d4d4d8;
    font-size: 11px;
    font-weight: 600;
}}
#IgiDrawerHeader:hover {{
    background-color: #292c37;
    color: #ffffff;
}}

#IgiDrawerBody {{
    background-color: #16171d;
    border-top: 1px solid #282a35;
    border-bottom-left-radius: 5px;
    border-bottom-right-radius: 5px;
    padding: 6px 8px;
}}

.ToolItemRow {{
    background-color: #1e1f27;
    border: 1px solid #2d303c;
    border-radius: 5px;
    padding: 6px 8px;
    margin: 3px 0;
}}

.ToolNameLabel {{
    font-family: 'Consolas', 'Fira Code', monospace;
    font-size: 11px;
    font-weight: 600;
    color: #38bdf8;
}}

.ToolDurationBadge {{
    font-family: 'Consolas', monospace;
    font-size: 10px;
    color: #10b981;
    background-color: #121318;
    border: 1px solid #252833;
    border-radius: 3px;
    padding: 1px 5px;
}}

.ToolDetailText {{
    font-family: 'Consolas', monospace;
    font-size: 10px;
    color: #a1a1aa;
    background-color: #131418;
    border-radius: 4px;
    padding: 4px 6px;
    margin-top: 3px;
}}

/* Interactive Policy Approval Card */
#IgiApprovalCard {{
    background-color: #201a14;
    border: 1px solid #d97706;
    border-radius: 8px;
    padding: 10px 12px;
    margin: 6px 0;
}}

#IgiApprovalTitle {{
    font-size: 12px;
    font-weight: 700;
    color: #f59e0b;
}}

#IgiApprovalDesc {{
    font-size: 11px;
    color: #e4e4e7;
    line-height: 1.4;
    margin: 4px 0;
}}

#IgiApprovalArgs {{
    font-family: 'Consolas', monospace;
    font-size: 10px;
    color: #38bdf8;
    background-color: #141416;
    border: 1px solid #2b2b34;
    border-radius: 4px;
    padding: 4px 8px;
    margin: 4px 0 8px 0;
}}

#IgiAllowBtn {{
    background-color: #059669;
    color: #ffffff;
    font-weight: 600;
    font-size: 11px;
    border: none;
    border-radius: 5px;
    padding: 6px 14px;
}}
#IgiAllowBtn:hover {{
    background-color: #10b981;
}}
#IgiAllowBtn:disabled {{
    background-color: #27272a;
    color: #71717a;
}}

#IgiDenyBtn {{
    background-color: #dc2626;
    color: #ffffff;
    font-weight: 600;
    font-size: 11px;
    border: none;
    border-radius: 5px;
    padding: 6px 14px;
}}
#IgiDenyBtn:hover {{
    background-color: #ef4444;
}}
#IgiDenyBtn:disabled {{
    background-color: #27272a;
    color: #71717a;
}}

#IgiApprovalStatus {{
    font-size: 11px;
    font-weight: 600;
    border-radius: 4px;
    padding: 3px 8px;
}}

/* Resizing Corner Grip */
QSizeGrip {{
    width: 14px;
    height: 14px;
    background: transparent;
}}

/* Input Area Container */
#IgiInputContainer {{
    background-color: {BG_HEADER};
    border-top: 1px solid {BORDER_MUTED};
    border-bottom-left-radius: 11px;
    border-bottom-right-radius: 11px;
    padding: 8px 12px;
}}

#IgiInputEdit {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER_MUTED};
    border-radius: 6px;
    color: #ffffff;
    padding: 7px 10px;
    font-size: 12px;
}}
#IgiInputEdit:focus {{
    border: 1px solid {BORDER_HIGHLIGHT};
}}

#IgiSendBtn {{
    background-color: #2b2e38;
    color: #f4f4f5;
    font-weight: 600;
    font-size: 12px;
    border: 1px solid #3b3e4a;
    border-radius: 6px;
    padding: 6px 14px;
}}
#IgiSendBtn:hover {{
    background-color: #383c4a;
    color: #ffffff;
}}

/* Subtle Minimalist Scrollbar */
QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: #2e303b;
    min-height: 20px;
    border-radius: 3px;
}}
QScrollBar::handle:vertical:hover {{
    background: #424654;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
"""
