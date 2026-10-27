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


def test_redact_text_api_keys():
    gate = PrivacyGatekeeper(enabled=True)
    # Dynamically assemble dummy test tokens so static scanners (e.g. GitHub Secret Scanning)
    # do not flag mock unit-test fixtures as real credentials.
    dummy_openrouter = "sk-" + "41bf191ffdc319cc" + "-" + "3c7age380cd9d4"
    dummy_anthropic = "sk-ant-" + "api03-" + "abcdef1234567890abcdef12345"
    dummy_github = "ghp_" + "1234567890" + "12345678901234567890123456"
    dummy_google = "AIza" + "SyD-" + "1234567890123456789012345678901"
    dummy_aws = "AKIA" + "IOSFODNN7EXAMPLE"

    sample_ocr = (
        f"Active terminal:\n"
        f"$env:OPENROUTER_API_KEY = {dummy_openrouter}\n"
        f"Anthropic: {dummy_anthropic}\n"
        f"GitHub: {dummy_github}\n"
        f"Google: {dummy_google}\n"
        f"AWS: {dummy_aws}\n"
        f"Safe text: python main.py run --interval 1.0"
    )
    sanitized, count, matched = gate.redact_text(sample_ocr)
    assert count >= 5
    assert dummy_openrouter not in sanitized
    assert dummy_anthropic not in sanitized
    assert dummy_github not in sanitized
    assert dummy_google not in sanitized
    assert dummy_aws not in sanitized
    assert "[REDACTED_API_KEY]" in sanitized
    assert "python main.py run" in sanitized


def test_blocked_window_titles_omniroute():
    gate = PrivacyGatekeeper("config/privacy_rules.json", enabled=True)
    res = gate.evaluate(app_name="Notepad.exe", window_title="omniroutecombo.txt - Notepad")
    assert not res.is_allowed
    assert res.action == "drop"

    res_env = gate.evaluate(app_name="code.exe", window_title=".env - myproject - Visual Studio Code")
    assert not res_env.is_allowed


if __name__ == "__main__":
    test_blocklist_blocks_sensitive_apps()
    test_redact_action()
    test_allowlist_mode()
    test_redact_text_api_keys()
    test_blocked_window_titles_omniroute()
    print("All Privacy Gatekeeper tests passed!")
