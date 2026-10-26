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
from typing import Any, List, Optional, Tuple

logger = logging.getLogger(__name__)


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


class PrivacyGatekeeper:
    """
    Evaluates active app, window title, and browser URL against security policies.
    Guarantees privacy as priority #1 for desktop memory recording.
    """

    def __init__(self, config_path: str | Path = "config/privacy_rules.json", enabled: bool = True):
        self.config_path = Path(config_path)
        self.enabled = enabled
        self._last_mtime: float = 0.0
        self.rules: PrivacyRules = PrivacyRules()
        self.reload_rules(force=True)

    def reload_rules(self, force: bool = False) -> None:
        """Reload privacy rules from disk if file was modified."""
        if not self.config_path.is_file():
            if force:
                logger.warning("Privacy rules file %s not found. Using empty blocklist.", self.config_path)
            return

        try:
            current_mtime = os.path.getmtime(self.config_path)
            if not force and current_mtime <= self._last_mtime:
                return

            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.rules = PrivacyRules(
                mode=data.get("mode", "blocklist").lower(),
                action_on_block=data.get("action_on_block", "drop").lower(),
                blocked_apps=[a.lower() for a in data.get("blocked_apps", [])],
                blocked_urls=data.get("blocked_urls", []),
                blocked_window_titles=data.get("blocked_window_titles", []),
                allowed_apps=[a.lower() for a in data.get("allowed_apps", ["*"])],
                allowed_urls=data.get("allowed_urls", ["*"]),
            )
            self._last_mtime = current_mtime
            logger.info("Loaded %d app, %d URL, and %d title privacy rules (mode=%s, on_block=%s).",
                        len(self.rules.blocked_apps),
                        len(self.rules.blocked_urls),
                        len(self.rules.blocked_window_titles),
                        self.rules.mode,
                        self.rules.action_on_block)
        except Exception as e:
            logger.error("Error reading privacy rules from %s: %s", self.config_path, e)

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
