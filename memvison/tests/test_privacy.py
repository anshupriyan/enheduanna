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


def test_url_query_secrets_google_signin_and_doc_hash():
    gate = PrivacyGatekeeper(enabled=True)

    # 1. Google sign-in link with OAuth state & code
    raw_google_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        "client_id=123456789.apps.googleusercontent.com&"
        "redirect_uri=https://example.com/oauth/callback&"
        "response_type=code&"
        "scope=openid%20email&"
        "state=4_0AY0e-g7SecRetOAuthStAte987654321&"
        "nonce=nonce1234567890abcdef"
    )
    sanitized_url, count, matched = gate.redact_url(raw_google_url)
    assert count >= 1
    assert "4_0AY0e-g7SecRetOAuthStAte987654321" not in sanitized_url
    assert "nonce1234567890abcdef" not in sanitized_url
    assert "client_id=123456789.apps.googleusercontent.com" in sanitized_url
    assert "state=[REDACTED_OAUTH_STATE]" in sanitized_url or "[REDACTED" in sanitized_url

    # 2. Document viewer URL with long viewer hash parameter
    doc_viewer_url = (
        "https://docs.google.com/viewer?"
        "docid=doc_abc123&"
        "hash=4a8f9b0c1d2e3f4a5b6c7d8e9f0a1b2c&"
        "authuser=0"
    )
    sanitized_doc, doc_count, _ = gate.redact_url(doc_viewer_url)
    assert doc_count >= 1
    assert "4a8f9b0c1d2e3f4a5b6c7d8e9f0a1b2c" not in sanitized_doc
    assert "[REDACTED_DOC_HASH]" in sanitized_doc or "[REDACTED" in sanitized_doc
    assert "docid=doc_abc123" in sanitized_doc

    # 3. Document viewer URL with long fragment hash (#...)
    hash_fragment_url = "https://example.com/viewer#8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c"
    sanitized_frag, frag_count, _ = gate.redact_url(hash_fragment_url)
    assert frag_count >= 1
    assert "8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c" not in sanitized_frag
    assert "[REDACTED_DOC_HASH]" in sanitized_frag

    # 4. Scrubber on OCR text containing URL with query secrets
    sample_text = (
        "User browser history:\n"
        "Navigated to https://login.example.com/authorize?client_id=myclient&state=oauthSecretState12345&code=authCode99887766\n"
        "Viewing document https://internal.corp/viewer#3f8a9b0c1d2e3f4a5b6c7d8e9f"
    )
    sanitized_text, text_count, text_matched = gate.redact_text(sample_text)
    assert text_count >= 2
    assert "oauthSecretState12345" not in sanitized_text
    assert "authCode99887766" not in sanitized_text
    assert "3f8a9b0c1d2e3f4a5b6c7d8e9f" not in sanitized_text
    assert "client_id=myclient" in sanitized_text


if __name__ == "__main__":
    test_blocklist_blocks_sensitive_apps()
    test_redact_action()
    test_allowlist_mode()
    test_redact_text_api_keys()
    test_blocked_window_titles_omniroute()
    test_url_query_secrets_google_signin_and_doc_hash()
    print("All Privacy Gatekeeper tests passed!")

