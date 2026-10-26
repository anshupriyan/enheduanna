"""
Command-Line Interface for mem-vision-mcp.
Allows running continuous capture, running single captures, querying memory, and testing privacy rules.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Add src to python path for direct execution
sys.path.insert(0, str(Path(__file__).parent / "src"))

from memvision.config import load_config
from memvision.engine import CaptureEngine
from memvision.privacy import PrivacyGatekeeper
from memvision.storage import MemoryStorage


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    format_str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(level=level, format=format_str, datefmt="%H:%M:%S")


def cmd_run(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    if args.interval:
        config.capture.interval_seconds = args.interval
    if args.threshold:
        config.capture.hash_threshold = args.threshold

    print("=" * 60)
    print("  🚀 Starting mem-vision-mcp Continuous Capture Loop")
    print(f"  • Interval: {config.capture.interval_seconds}s")
    print(f"  • Perceptual Hash: {config.capture.hash_algorithm} (threshold: {config.capture.hash_threshold})")
    print(f"  • Database: {config.storage.database_path}")
    print(f"  • Screenshots: {config.storage.screenshots_dir}")
    print(f"  • Privacy Rules: {config.privacy.config_path}")
    print("  Press Ctrl+C to stop gracefully.")
    print("=" * 60)

    engine = CaptureEngine(config)
    engine.run()


def cmd_once(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    engine = CaptureEngine(config)
    print("Capturing single screen frame...")
    record = engine.capture_once(force=args.force)
    if record:
        print("\n✅ Capture successful!")
        print(f"  • Record ID:       {record.id}")
        print(f"  • Timestamp:       {record.timestamp}")
        print(f"  • App Name:        {record.app_name}")
        print(f"  • Window Title:    {record.window_title}")
        print(f"  • Browser URL:     {record.url}")
        print(f"  • Perceptual Hash: {record.phash}")
        print(f"  • Screenshot File: {record.screenshot_path}")
        print(f"  • Extracted OCR:   {len(record.ocr_text)} characters")
        if record.ocr_text:
            snippet = record.ocr_text.strip().replace("\n", " ")[:200]
            print(f"    Preview: \"{snippet}...\"")
    else:
        print("\nℹ️ No capture produced (screen unchanged or dropped by Privacy Gatekeeper).")


def cmd_search(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    storage = MemoryStorage(config.storage.database_path, config.storage.enable_fts)
    results = storage.search(args.query, limit=args.limit)

    print(f"\n🔍 Search Results for: \"{args.query}\" (Found: {len(results)})")
    print("-" * 60)
    if not results:
        print("  No matching records found.")
        return

    for r in results:
        redacted_badge = " [REDACTED]" if r.is_redacted else ""
        print(f"ID #{r.id} | {r.timestamp[:19]} | {r.app_name}{redacted_badge}")
        if r.window_title:
            print(f"  Title: {r.window_title}")
        if r.url:
            print(f"  URL:   {r.url}")
        if r.ocr_text:
            snippet = r.ocr_text.strip().replace("\n", " ")[:140]
            print(f"  OCR:   {snippet}...")
        print("-" * 60)


def cmd_stats(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    storage = MemoryStorage(config.storage.database_path)
    stats = storage.get_stats()
    print("\n📊 mem-vision-mcp Memory Storage Statistics")
    print("=" * 45)
    for k, v in stats.items():
        print(f"  {k:28}: {v}")
    print("=" * 45)


def cmd_privacy_test(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    gatekeeper = PrivacyGatekeeper(config.privacy.config_path, enabled=True)
    decision = gatekeeper.evaluate(
        app_name=args.app,
        window_title=args.title,
        url=args.url,
    )
    print("\n🔒 Privacy Gatekeeper Evaluation Result")
    print("-" * 45)
    print(f"  Input App:     {args.app}")
    print(f"  Input Title:   {args.title}")
    print(f"  Input URL:     {args.url}")
    print(f"  Allowed:       {'✅ YES' if decision.is_allowed else '❌ NO'}")
    print(f"  Action:        {decision.action.upper()}")
    print(f"  Reason:        {decision.reason}")
    print(f"  Matched Rule:  {decision.matched_rule}")
    print("-" * 45)


def cmd_open(args: argparse.Namespace) -> None:
    import os
    config = load_config(args.config)
    target_dir = Path(config.storage.screenshots_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    print(f"Opening screenshots folder in Windows Explorer:\n  {target_dir}")
    os.startfile(str(target_dir))


def cmd_latest(args: argparse.Namespace) -> None:
    import os
    config = load_config(args.config)
    storage = MemoryStorage(config.storage.database_path)
    recent = storage.get_recent(limit=1)
    if not recent:
        print("No captures found in memory storage yet.")
        return

    r = recent[0]
    print("\n📸 Latest Capture:")
    print(f"  • ID:          {r.id}")
    print(f"  • Timestamp:   {r.timestamp}")
    print(f"  • App:         {r.app_name}")
    print(f"  • Title:       {r.window_title}")
    print(f"  • URL:         {r.url}")
    print(f"  • Screenshot:  {r.screenshot_path}")
    if r.ocr_text:
        preview = r.ocr_text.strip().replace("\n", " ")[:140]
        print(f"  • OCR Preview: {preview}...")

    if args.view and r.screenshot_path and Path(r.screenshot_path).is_file():
        print(f"\nOpening image in default viewer: {r.screenshot_path}")
        os.startfile(r.screenshot_path)


def cmd_chat(args: argparse.Namespace) -> None:
    from memvision.ai_chat import AIChatEngine
    config = load_config(args.config)
    chat_engine = AIChatEngine(config)
    creds = chat_engine.get_api_credentials()

    print("=" * 60)
    print("  💬 mem-vision-mcp AI Memory Chat")
    print(f"  • Provider: {creds.get('provider', 'custom').upper()}")
    print(f"  • Model:    {creds['model']}")
    print(f"  • Endpoint: {creds['base_url']}")
    print(f"  • API Key:  {'Configured' if creds['api_key'] else 'Not set (using local retrieval summary)'}")
    print("  Type 'exit' or 'quit' to leave.")
    print("=" * 60)

    if args.query:
        _run_chat_query(chat_engine, args.query)
        return

    while True:
        try:
            user_input = input("\nAsk your memory > ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "q"):
                print("Goodbye!")
                break
            _run_chat_query(chat_engine, user_input)
        except (KeyboardInterrupt, EOFError):
            print("\nExiting chat.")
            break


def _run_chat_query(engine, query: str) -> None:
    print(f"\nSearching memory for: \"{query}\"...")
    resp = engine.ask(query)
    print(f"\n🤖 Answer ({resp.model_used}):")
    print("-" * 60)
    print(resp.answer)
    print("-" * 60)
    if resp.citations:
        print(f"📚 References used ({len(resp.citations)} captures):")
        for i, c in enumerate(resp.citations, 1):
            url_str = f" | {c.url}" if c.url else ""
            print(f"  [{i}] ID #{c.id} | {c.timestamp[:19].replace('T', ' ')} | {c.app_name}{url_str}")


def cmd_mcp(args: argparse.Namespace) -> None:
    from memvision.mcp_server import MCPServer
    config = load_config(args.config)
    server = MCPServer(config.storage.database_path)
    server.run_stdio()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mem-vision-mcp",
        description="Local-first, privacy-first continuous desktop memory capture loop.",
    )
    parser.add_argument("-c", "--config", default="config/default_config.json", help="Path to config JSON")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose/debug logging")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # run command
    run_parser = subparsers.add_parser("run", help="Start continuous capture loop")
    run_parser.add_argument("--interval", type=float, help="Sampling interval in seconds")
    run_parser.add_argument("--threshold", type=int, help="Perceptual hash difference threshold")

    # once command
    once_parser = subparsers.add_parser("once", help="Capture a single frame")
    once_parser.add_argument("-f", "--force", action="store_true", help="Bypass change detection threshold")

    # search command
    search_parser = subparsers.add_parser("search", help="Search desktop memory using FTS5")
    search_parser.add_argument("query", help="Keywords to search in window titles, URLs, or OCR text")
    search_parser.add_argument("-l", "--limit", type=int, default=10, help="Max results to return")

    # chat command
    chat_parser = subparsers.add_parser("chat", help="Chat with your desktop memory using AI")
    chat_parser.add_argument("query", nargs="?", help="Optional direct question to ask")

    # mcp command
    subparsers.add_parser("mcp", help="Launch Model Context Protocol (MCP) JSON-RPC stdio server")

    # stats command
    subparsers.add_parser("stats", help="Display memory storage statistics")

    # privacy-test command
    priv_parser = subparsers.add_parser("privacy-test", help="Test active context against privacy rules")
    priv_parser.add_argument("--app", default="", help="Process name to test (e.g. 1password.exe)")
    priv_parser.add_argument("--title", default="", help="Window title to test")
    priv_parser.add_argument("--url", default="", help="URL to test")

    # open command
    subparsers.add_parser("open", help="Open the screenshots folder in Windows Explorer")

    # latest command
    latest_parser = subparsers.add_parser("latest", help="Show the most recent capture")
    latest_parser.add_argument("--view", action="store_true", help="Open the screenshot image in default photo viewer")

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.command == "run":
        cmd_run(args)
    elif args.command == "once":
        cmd_once(args)
    elif args.command == "search":
        cmd_search(args)
    elif args.command == "chat":
        cmd_chat(args)
    elif args.command == "mcp":
        cmd_mcp(args)
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "privacy-test":
        cmd_privacy_test(args)
    elif args.command == "open":
        cmd_open(args)
    elif args.command == "latest":
        cmd_latest(args)


if __name__ == "__main__":
    main()
