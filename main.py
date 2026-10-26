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

    # stats command
    subparsers.add_parser("stats", help="Display memory storage statistics")

    # privacy-test command
    priv_parser = subparsers.add_parser("privacy-test", help="Test active context against privacy rules")
    priv_parser.add_argument("--app", default="", help="Process name to test (e.g. 1password.exe)")
    priv_parser.add_argument("--title", default="", help="Window title to test")
    priv_parser.add_argument("--url", default="", help="URL to test")

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.command == "run":
        cmd_run(args)
    elif args.command == "once":
        cmd_once(args)
    elif args.command == "search":
        cmd_search(args)
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "privacy-test":
        cmd_privacy_test(args)


if __name__ == "__main__":
    main()
