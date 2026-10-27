"""
Privacy Gatekeeper for mem-vision-mcp.
Enforces allowlist / blocklist privacy boundaries before screen capture, OCR, or storage.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_project_root = Path(__file__).resolve().parent.parent.parent

DEFAULT_REDACTION_PATTERNS: List[Dict[str, str]] = [
    {
        "name": "Standard API Keys (OpenAI, OpenRouter, Anthropic, DeepSeek)",
        "pattern": r"\b(?:sk-[a-zA-Z0-9_\-]{14,}|sk-or-v1-[a-zA-Z0-9_\-]{14,}|sk-ant-[a-zA-Z0-9_\-]{14,})\b",
        "replacement": "[REDACTED_API_KEY]",
    },
    {
        "name": "GitHub Access & OAuth Tokens",
        "pattern": r"\bgh[pousr]_[a-zA-Z0-9]{36,255}\b",
        "replacement": "[REDACTED_GITHUB_TOKEN]",
    },
    {
        "name": "Google API Keys",
        "pattern": r"\bAIza[0-9A-Za-z-_]{35}\b",
        "replacement": "[REDACTED_GOOGLE_KEY]",
    },
    {
        "name": "AWS Access Keys",
        "pattern": r"\b(?:AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b",
        "replacement": "[REDACTED_AWS_KEY]",
    },
    {
        "name": "HuggingFace Access Tokens",
        "pattern": r"\bhf_[a-zA-Z0-9]{34,}\b",
        "replacement": "[REDACTED_HF_TOKEN]",
    },
    {
        "name": "Slack API Tokens",
        "pattern": r"\bxox[baprs]-[0-9a-zA-Z]{10,48}\b",
        "replacement": "[REDACTED_SLACK_TOKEN]",
    },
    {
        "name": "Bearer Auth Tokens",
        "pattern": r"(?i)\bBearer\s+([a-zA-Z0-9_\-\.~+/]{20,})\b",
        "replacement": "Bearer [REDACTED_BEARER_TOKEN]",
    },
    {
        "name": "Variable Key/Secret/Password Assignments",
        "pattern": r"(?i)\b(?:api[\s_-]?key|secret|password|access[\s_-]?token|auth[\s_-]?token|private[\s_-]?key)\s*[:=\-]+\s*['\"]?([a-zA-Z0-9_\-\.~+/]{12,})['\"]?",
        "replacement": "[REDACTED_SECRET]",
    },
    {
        "name": "JSON Web Tokens (JWT)",
        "pattern": r"\beyJ[a-zA-Z0-9_\-]{10,}\.eyJ[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]+\b",
        "replacement": "[REDACTED_JWT]",
    },
    {
        "name": "Private Key Headers",
        "pattern": r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
        "replacement": "[REDACTED_PRIVATE_KEY_BLOCK]",
    },
]


@dataclass
class PrivacyDecision:
    """Represents the verdict of the privacy gatekeeper."""
    is_allowed: bool
    action: str  # "pass", "drop", or "redact"
    reason: str
    matched_rule: Optional[str] = None


@dataclass
class PrivacyRules:
    mode: str = "blocklist"  # "blocklist" or "allowlist"
    action_on_block: str = "drop"  # "drop" or "redact"
    blocked_apps: List[str] = field(default_factory=list)
    blocked_urls: List[str] = field(default_factory=list)
    blocked_window_titles: List[str] = field(default_factory=list)
    allowed_apps: List[str] = field(default_factory=lambda: ["*"])
    allowed_urls: List[str] = field(default_factory=lambda: ["*"])
    redacted_text_patterns: List[Dict[str, str]] = field(default_factory=list)


class PrivacyGatekeeper:
    """
    Evaluates active app, window title, and browser URL against security policies.
    Guarantees privacy as priority #1 for desktop memory recording.
    """

    def __init__(self, config_path: str | Path = "config/privacy_rules.json", enabled: bool = True):
        p = Path(config_path)
        if not p.is_file() and not p.is_absolute():
            p = _project_root / p
        self.config_path = p
        self.enabled = enabled
        self._last_mtime: float = 0.0
        self.rules: PrivacyRules = PrivacyRules()
        self._compiled_redaction_patterns: List[Tuple[str, re.Pattern, str]] = []
        self.reload_rules(force=True)

    def reload_rules(self, force: bool = False) -> None:
        """Reload privacy rules from disk if file was modified."""
        if not self.config_path.is_file():
            if force:
                logger.warning("Privacy rules file %s not found. Using default redaction patterns.", self.config_path)
                self._compile_redaction_patterns([])
            return

        try:
            current_mtime = os.path.getmtime(self.config_path)
            if not force and current_mtime <= self._last_mtime:
                return

            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            raw_patterns = data.get("redacted_text_patterns", [])

            self.rules = PrivacyRules(
                mode=data.get("mode", "blocklist").lower(),
                action_on_block=data.get("action_on_block", "drop").lower(),
                blocked_apps=[a.lower() for a in data.get("blocked_apps", [])],
                blocked_urls=data.get("blocked_urls", []),
                blocked_window_titles=data.get("blocked_window_titles", []),
                allowed_apps=[a.lower() for a in data.get("allowed_apps", ["*"])],
                allowed_urls=data.get("allowed_urls", ["*"]),
                redacted_text_patterns=raw_patterns,
            )
            self._compile_redaction_patterns(raw_patterns)
            self._last_mtime = current_mtime
            logger.info("Loaded %d app, %d URL, %d title rules, and %d text redaction patterns (mode=%s).",
                        len(self.rules.blocked_apps),
                        len(self.rules.blocked_urls),
                        len(self.rules.blocked_window_titles),
                        len(self._compiled_redaction_patterns),
                        self.rules.mode)
        except Exception as e:
            logger.error("Error reading privacy rules from %s: %s", self.config_path, e)

    def _compile_redaction_patterns(self, custom_patterns: List[Any]) -> None:
        """Compiles custom + default regex redaction patterns."""
        compiled: List[Tuple[str, re.Pattern, str]] = []
        seen_patterns = set()

        # 1. Custom patterns from config
        for item in custom_patterns:
            if isinstance(item, dict):
                pat = item.get("pattern", "")
                name = item.get("name", "Custom Pattern")
                repl = item.get("replacement", "[REDACTED_SECRET]")
            elif isinstance(item, str):
                pat = item
                name = "Custom Pattern"
                repl = "[REDACTED_SECRET]"
            else:
                continue

            if pat and pat not in seen_patterns:
                try:
                    compiled.append((name, re.compile(pat), repl))
                    seen_patterns.add(pat)
                except re.error as e:
                    logger.warning("Invalid regex in privacy pattern '%s': %s", pat, e)

        # 2. Add built-in defaults if not already present
        for default_item in DEFAULT_REDACTION_PATTERNS:
            pat = default_item["pattern"]
            if pat not in seen_patterns:
                try:
                    compiled.append((default_item["name"], re.compile(pat), default_item["replacement"]))
                    seen_patterns.add(pat)
                except re.error as e:
                    logger.warning("Invalid default regex '%s': %s", pat, e)

        self._compiled_redaction_patterns = compiled

    def redact_text(self, text: Optional[str]) -> Tuple[str, int, List[str]]:
        """
        Scans text for sensitive tokens, API keys, credentials, and passwords,
        replacing matches with safe redaction placeholders.
        Returns:
            (sanitized_text, count_of_redactions, list_of_matched_rule_names)
        """
        if not text or not self.enabled:
            return text or "", 0, []

        self.reload_rules(force=False)

        sanitized = text
        total_redacted = 0
        matched_names: List[str] = []

        for name, pattern_re, replacement in self._compiled_redaction_patterns:
            matches = list(pattern_re.finditer(sanitized))
            if matches:
                total_redacted += len(matches)
                matched_names.append(name)

                def _replace_match(m: re.Match) -> str:
                    if m.groups() and len(m.groups()) == 1 and m.group(1):
                        full = m.group(0)
                        secret = m.group(1)
                        return full.replace(secret, replacement)
                    return replacement

                sanitized = pattern_re.sub(_replace_match, sanitized)

        return sanitized, total_redacted, matched_names

    @staticmethod
    def _matches_pattern(value: str, pattern: str) -> bool:
        """Case-insensitive pattern matching supporting wildcards (*) and regex."""
        if not value or not pattern:
            return False
        val_clean = value.strip().lower()
        pat_clean = pattern.strip().lower()

        # Direct equality or wildcard matching
        if fnmatch.fnmatch(val_clean, pat_clean):
            return True

        # Regex fallback for patterns starting with ^ or containing regex tokens
        if any(c in pattern for c in r"^$[]()+{}"):
            try:
                if re.search(pattern, value, re.IGNORECASE):
                    return True
            except re.error:
                pass

        return False

    def evaluate(self, app_name: Optional[str], window_title: Optional[str] = None, url: Optional[str] = None) -> PrivacyDecision:
        """
        Evaluate context against privacy policies.
        Returns a PrivacyDecision indicating whether capture is permitted and the action to take.
        """
        if not self.enabled:
            return PrivacyDecision(is_allowed=True, action="pass", reason="Privacy gatekeeper disabled")

        # Periodically check for updated config
        self.reload_rules(force=False)

        app = (app_name or "").lower().strip()
        title = (window_title or "").strip()
        browser_url = (url or "").strip()

        # 1. Check Allowlist Mode
        if self.rules.mode == "allowlist":
            app_allowed = any(self._matches_pattern(app, pattern) for pattern in self.rules.allowed_apps)
            if not app_allowed:
                return PrivacyDecision(
                    is_allowed=False,
                    action=self.rules.action_on_block,
                    reason=f"App '{app}' is not in allowlist",
                    matched_rule="allowed_apps",
                )

            if browser_url and self.rules.allowed_urls != ["*"]:
                url_allowed = any(self._matches_pattern(browser_url, pat) for pat in self.rules.allowed_urls)
                if not url_allowed:
                    return PrivacyDecision(
                        is_allowed=False,
                        action=self.rules.action_on_block,
                        reason=f"URL '{browser_url}' is not in allowlist",
                        matched_rule="allowed_urls",
                    )

            return PrivacyDecision(is_allowed=True, action="pass", reason="Allowed by allowlist policy")

        # 2. Blocklist Mode (Default)
        # Check blocked applications (e.g. password managers, security apps)
        for blocked_app in self.rules.blocked_apps:
            if self._matches_pattern(app, blocked_app):
                return PrivacyDecision(
                    is_allowed=False,
                    action=self.rules.action_on_block,
                    reason=f"Blocked application matched: '{blocked_app}'",
                    matched_rule=blocked_app,
                )

        # Check blocked window titles (e.g. Incognito, InPrivate, Password Dialogs)
        if title:
            for blocked_title in self.rules.blocked_window_titles:
                if self._matches_pattern(title, blocked_title):
                    return PrivacyDecision(
                        is_allowed=False,
                        action=self.rules.action_on_block,
                        reason=f"Blocked window title matched: '{blocked_title}'",
                        matched_rule=blocked_title,
                    )

        # Check blocked URLs (e.g. banking, crypto, settings, auth)
        if browser_url:
            for blocked_url in self.rules.blocked_urls:
                if self._matches_pattern(browser_url, blocked_url):
                    return PrivacyDecision(
                        is_allowed=False,
                        action=self.rules.action_on_block,
                        reason=f"Blocked URL pattern matched: '{blocked_url}'",
                        matched_rule=blocked_url,
                    )

        return PrivacyDecision(is_allowed=True, action="pass", reason="Passed all privacy checks")

    def filter_blocked_windows(
        self, windows: List[Any]
    ) -> List[Tuple[Any, PrivacyDecision]]:
        """
        Evaluates a collection of visible desktop windows against privacy policies.
        Returns a list of (VisibleWindow, PrivacyDecision) for each window violating privacy rules.
        """
        if not self.enabled:
            return []

        blocked: List[Tuple[Any, PrivacyDecision]] = []
        for win in windows:
            decision = self.evaluate(
                app_name=getattr(win, "app_name", ""),
                window_title=getattr(win, "window_title", ""),
                url=None,
            )
            if not decision.is_allowed:
                blocked.append((win, decision))
        return blocked
