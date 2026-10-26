"""
Unit tests for Privacy Gatekeeper.
"""

import json
import tempfile
from pathlib import Path
from memvision.privacy import PrivacyGatekeeper


def test_blocklist_blocks_sensitive_apps():
    rules = {
        "mode": "blocklist",
        "action_on_block": "drop",
        "blocked_apps": ["1password.exe", "bitwarden.exe"],
        "blocked_urls": ["*paypal.com*"],
        "blocked_window_titles": ["*Incognito*"],
    }
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f:
        json.dump(rules, f)
        rule_path = f.name

    try:
        gate = PrivacyGatekeeper(rule_path, enabled=True)

        # 1. Blocked App
        res = gate.evaluate(app_name="1password.exe")
        assert not res.is_allowed
        assert res.action == "drop"

        # 2. Blocked URL
        res = gate.evaluate(app_name="chrome.exe", url="https://www.paypal.com/signin")
        assert not res.is_allowed
        assert res.action == "drop"

        # 3. Blocked Title
        res = gate.evaluate(app_name="chrome.exe", window_title="New Tab - Incognito")
        assert not res.is_allowed
        assert res.action == "drop"

        # 4. Safe App & Safe URL
        res = gate.evaluate(app_name="code.exe", window_title="main.py - memvision", url=None)
        assert res.is_allowed
        assert res.action == "pass"

    finally:
        Path(rule_path).unlink(missing_ok=True)


def test_redact_action():
    rules = {
        "mode": "blocklist",
        "action_on_block": "redact",
        "blocked_apps": ["keepass.exe"],
    }
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f:
        json.dump(rules, f)
        rule_path = f.name

    try:
        gate = PrivacyGatekeeper(rule_path, enabled=True)
        res = gate.evaluate(app_name="keepass.exe")
        assert not res.is_allowed
        assert res.action == "redact"
    finally:
        Path(rule_path).unlink(missing_ok=True)


def test_allowlist_mode():
    rules = {
        "mode": "allowlist",
        "action_on_block": "drop",
        "allowed_apps": ["code.exe", "chrome.exe"],
        "allowed_urls": ["*github.com*"],
    }
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f:
        json.dump(rules, f)
        rule_path = f.name

    try:
        gate = PrivacyGatekeeper(rule_path, enabled=True)

        # Allowed app and allowed URL
        res = gate.evaluate(app_name="chrome.exe", url="https://github.com/meta/hackathon")
        assert res.is_allowed

        # Allowed app but unallowed URL
        res = gate.evaluate(app_name="chrome.exe", url="https://random-site.com")
        assert not res.is_allowed

        # Unallowed app
        res = gate.evaluate(app_name="slack.exe")
        assert not res.is_allowed
    finally:
        Path(rule_path).unlink(missing_ok=True)


if __name__ == "__main__":
    test_blocklist_blocks_sensitive_apps()
    test_redact_action()
    test_allowlist_mode()
    print("All Privacy Gatekeeper tests passed!")
