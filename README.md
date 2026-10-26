# mem-vision-mcp

> **A local-first, privacy-first continuous desktop memory layer that captures screen context, understands UI structure, and exposes memory via Model Context Protocol (MCP) tools for AI agents.**

Built for the **Meta Global AI Developer Hackathon**. 100% open-source with permissive licenses (MIT, BSD, Apache 2.0).

---

## Architecture Overview

`mem-vision-mcp` is designed as a lightweight, zero-cloud desktop background daemon with five decoupled subsystems:

```
                  ┌────────────────────────────────────────┐
                  │          Continuous Screen Loop         │
                  └───────────────────┬────────────────────┘
                                      │
                         [Screen Capturer: mss/GDI]
                                      │
                         [Perceptual Change Detector]
                                      │ (Diff > Threshold)
                         ┌────────────┴────────────┐
                         │    Context Extractor    │
                         │  (Active App, Title,    │
                         │   Browser Active URL)   │
                         └────────────┬────────────┘
                                      │
                    ══════════════════▼══════════════════
                    🔒 PRIVACY GATEKEEPER (Priority #1)
                    - Check App against Blocklist
                    - Check URL against Blocklist
                    - Check Window Title against Regex
                    ══════════════════┬══════════════════
                          /                       \
                  [BLOCKED]                       [PASSED]
                     /                               \
        ┌───────────────────────────┐         ┌───────────────────────────────┐
        │  Action: DROP or REDACT   │         │  Local OCR (WinRT / Tesseract)│
        │  - Drop: Discard entirely │         │  - Windows Native WinRT OCR   │
        │  - Redact: Masked stub    │         │  - 0 Network, ~70ms latency   │
        └───────────────────────────┘         └───────────────┬───────────────┘
                                                              │
                                              ┌───────────────▼───────────────┐
                                              │    Local SQLite + FTS5 Index  │
                                              │  - WAL mode (high-throughput) │
                                              │  - Full-text keyword search   │
                                              │  - Compressed JPEG / WebP     │
                                              └───────────────────────────────┘
```

---

## Open-Source License Compliance

Every dependency is strictly permissively licensed:

| Package | Version | License | Role |
| :--- | :--- | :--- | :--- |
| **mss** | `>=10.2.0` | **MIT** | Ultra-fast screen capture via native Windows GDI/DirectX |
| **Pillow** | `>=10.0.0` | **HPND / Open-Source** | Image scaling, compression, JPEG/WebP serialization |
| **imagehash** | `>=4.3.1` | **BSD-2-Clause** | Difference hashing (`dhash`) & perceptual hashing (`phash`) |
| **numpy** | `>=1.26.0` | **BSD-3-Clause** | Fast matrix operations for hashing |
| **psutil** | `>=5.9.0` | **BSD-3-Clause** | Process name and system context identification |
| **pywin32** | `>=306` | **PSF / BSD** | Windows Win32 API bindings |
| **uiautomation**| `>=2.0.19` | **Apache-2.0** | Windows UI Automation to extract active browser tab URLs |
| **winrt-*** | `>=4.0.0` | **MIT** | Microsoft official WinRT bindings for on-device native OCR |
| **pytesseract** | `>=0.3.10` | **Apache-2.0** | Fallback OCR engine |
| **sqlite3** | Built-in | **Public Domain** | SQLite database with FTS5 full-text indexing |

---

## Project Structure

```
memvison/
├── config/
│   ├── default_config.json      # Capture intervals, OCR config, storage paths
│   └── privacy_rules.json       # Privacy Gatekeeper rules (apps, URLs, titles)
├── data/
│   ├── memvision.db             # Local SQLite database with FTS5 search
│   └── screenshots/             # Stored screenshot images (.jpg / .webp)
├── src/
│   └── memvision/
│       ├── __init__.py          # Package exports
│       ├── config.py            # Typed dataclasses & JSON config loader
│       ├── privacy.py           # Privacy Gatekeeper (allowlist/blocklist engine)
│       ├── capture.py           # Windows screen capture engine (mss + PIL fallback)
│       ├── change_detector.py   # Perceptual hasher (dhash/phash, hamming distance)
│       ├── context.py           # Active window & URL extractor (Win32 + UI Automation)
│       ├── ocr.py               # Windows native WinRT OCR engine + fallback
│       ├── storage.py           # SQLite storage manager with FTS5 search & triggers
│       └── engine.py            # Continuous capture loop orchestrator
├── tests/
│   ├── test_privacy.py          # Unit tests for Privacy Gatekeeper
│   ├── test_change_detector.py  # Unit tests for perceptual hashing
│   └── test_storage.py          # Unit tests for SQLite & FTS5 full-text search
├── main.py                      # CLI entry point (run, once, search, stats, privacy-test)
├── requirements.txt             # Pinned open-source dependencies
├── LICENSE                      # MIT License
└── README.md                    # Documentation & setup instructions
```

---

## Privacy Gatekeeper Specification

Privacy is the **#1 priority** of `mem-vision-mcp`. The gatekeeper inspects context **before** OCR or disk writes:

1. **Policy Modes**:
   - `blocklist` (default): Captures everything except blocked apps, URLs, and titles.
   - `allowlist`: Blocks everything except explicitly allowed applications and domains.
2. **Action on Block**:
   - `drop` (default): Discards the capture completely. Zero bytes written to disk, zero OCR processed.
   - `redact`: Saves a sanitized audit stub in SQLite (`is_redacted = 1`) with masked title and no screenshot file.
3. **Built-in Protection**:
   - **Password Managers**: 1Password, Bitwarden, KeePass, LastPass, Dashlane, Enpass.
   - **Authentication**: Windows Credential UI, Consent dialogs, Authenticator apps.
   - **Financial Domains**: Banking portals, PayPal, Chase, Bank of America, Fidelity, Coinbase.
   - **Private Windows**: Incognito, InPrivate, and Private Browsing tabs.
4. **Hot Reloading**: Edit `config/privacy_rules.json` at any time; rules reload automatically without restarting the engine.

---

## Quickstart & Verification

### 1. Prerequisites
- **OS**: Windows 10 or Windows 11 (64-bit)
- **Python**: Python 3.11 or 3.12 (CPython)

### 2. Setup Virtual Environment
Using `uv` (recommended):
```powershell
uv venv .venv --python 3.12
uv pip install --python .\.venv\Scripts\python.exe -r requirements.txt
```

Or using standard `python`:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Run Automated Unit Tests
```powershell
.\.venv\Scripts\python tests\test_privacy.py
.\.venv\Scripts\python tests\test_change_detector.py
.\.venv\Scripts\python tests\test_storage.py
```

### 4. CLI Commands & Verification

#### A. Test Privacy Rules
Verify that sensitive apps, banking URLs, or private windows are blocked:
```powershell
# Blocked password manager
.\.venv\Scripts\python main.py privacy-test --app 1password.exe

# Blocked banking URL
.\.venv\Scripts\python main.py privacy-test --app chrome.exe --url "https://www.chase.com"

# Allowed development tool
.\.venv\Scripts\python main.py privacy-test --app Code.exe --title "main.py - memvision"
```

#### B. Single Frame Capture (On-Demand)
Capture a single frame to verify the pipeline (Capture → Perceptual Hash → Context → Privacy → WinRT OCR → SQLite):
```powershell
.\.venv\Scripts\python main.py once -f
```

#### C. Full-Text Search in Desktop Memory
Search across past captures using SQLite's FTS5 engine:
```powershell
.\.venv\Scripts\python main.py search "Antigravity"
.\.venv\Scripts\python main.py search "Meta Hackathon"
```

#### D. View Storage Statistics
```powershell
.\.venv\Scripts\python main.py stats
```

#### E. Start Continuous Capture Loop
Run the continuous background memory recorder:
```powershell
.\.venv\Scripts\python main.py run --interval 1.0 --threshold 3
```
*Press `Ctrl+C` to cleanly stop.*
