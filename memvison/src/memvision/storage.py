"""
SQLite and FTS5 Storage Engine for mem-vision-mcp.
Provides high-performance persistent storage and instant full-text search over captured memory.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class CaptureRecord:
    id: Optional[int] = None
    timestamp: str = ""
    app_name: str = ""
    window_title: str = ""
    url: Optional[str] = None
    ocr_text: str = ""
    screenshot_path: Optional[str] = None
    phash: str = ""
    width: int = 0
    height: int = 0
    is_redacted: int = 0
    metadata: Optional[Dict[str, Any]] = None
    episode_id: Optional[int] = None
    file_path: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


@dataclass
class EpisodeRecord:
    id: Optional[int] = None
    app_name: str = ""
    title: str = ""
    url: Optional[str] = None
    start_time: str = ""
    end_time: str = ""
    duration_seconds: int = 0
    capture_count: int = 1
    key_capture_id: Optional[int] = None
    screenshot_path: Optional[str] = None
    summary_keywords: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WindowRecord:
    id: Optional[int] = None
    capture_id: int = 0
    hwnd: Optional[int] = None
    app_name: str = ""
    pid: Optional[int] = None
    title: Optional[str] = ""
    url: Optional[str] = None
    rect_x: int = 0
    rect_y: int = 0
    rect_w: int = 0
    rect_h: int = 0
    z_index: int = 0
    is_foreground: int = 0
    monitor: Optional[str] = "Primary"
    visible_fraction: float = 1.0
    ocr_text: str = ""
    ocr_lines: Optional[str] = None
    text_hash: Optional[str] = None
    crop_path: Optional[str] = None
    created_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.ocr_lines and isinstance(self.ocr_lines, str):
            try:
                d["ocr_lines"] = json.loads(self.ocr_lines)
            except Exception:
                pass
        return d


class MemoryStorage:
    """
    Manages local SQLite database and FTS5 full-text index for screen captures.
    Optimized with WAL mode for fast concurrent reads and writes.
    """

    def __init__(self, db_path: str | Path = "data/memvision.db", enable_fts: bool = True):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.enable_fts = enable_fts
        self._init_database()

    from contextlib import contextmanager

    @contextmanager
    def connection(self):
        """Context manager that provides and automatically closes a SQLite connection."""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
        finally:
            conn.close()

    def _init_database(self) -> None:
        """Initialize tables, indexes, and full-text search triggers."""
        with self.connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS captures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    app_name TEXT NOT NULL,
                    window_title TEXT,
                    url TEXT,
                    ocr_text TEXT,
                    screenshot_path TEXT,
                    phash TEXT,
                    width INTEGER DEFAULT 0,
                    height INTEGER DEFAULT 0,
                    is_redacted INTEGER DEFAULT 0,
                    metadata TEXT
                );
            """)

            conn.execute("CREATE INDEX IF NOT EXISTS idx_captures_timestamp ON captures(timestamp);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_captures_app ON captures(app_name);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_captures_phash ON captures(phash);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_captures_app_time ON captures(app_name, timestamp DESC);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_captures_time_desc ON captures(timestamp DESC);")

            # Setup windows table for Per-Window Spatial Memory
            conn.execute("""
                CREATE TABLE IF NOT EXISTS windows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    capture_id INTEGER NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
                    hwnd INTEGER,
                    app_name TEXT NOT NULL,
                    pid INTEGER,
                    title TEXT,
                    url TEXT,
                    rect_x INTEGER DEFAULT 0,
                    rect_y INTEGER DEFAULT 0,
                    rect_w INTEGER DEFAULT 0,
                    rect_h INTEGER DEFAULT 0,
                    z_index INTEGER DEFAULT 0,
                    is_foreground INTEGER DEFAULT 0,
                    monitor TEXT,
                    visible_fraction REAL DEFAULT 1.0,
                    ocr_text TEXT,
                    ocr_lines TEXT,
                    text_hash TEXT,
                    crop_path TEXT,
                    created_at TEXT
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_windows_capture_id ON windows(capture_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_windows_app_name ON windows(app_name);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_windows_text_hash ON windows(text_hash);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_windows_foreground ON windows(is_foreground);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_windows_time ON windows(created_at);")

            # Setup episodes table for Session / Scene Clustering (Option B)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    app_name TEXT NOT NULL,
                    title TEXT,
                    url TEXT,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    duration_seconds INTEGER DEFAULT 0,
                    capture_count INTEGER DEFAULT 1,
                    key_capture_id INTEGER,
                    screenshot_path TEXT,
                    summary_keywords TEXT
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_time ON episodes(start_time DESC);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_app ON episodes(app_name);")

            # Migration: Ensure episode_id and file_path columns exist on captures table
            cursor = conn.execute("PRAGMA table_info(captures);")
            cols = [r[1] for r in cursor.fetchall()]
            if "episode_id" not in cols:
                try:
                    conn.execute("ALTER TABLE captures ADD COLUMN episode_id INTEGER REFERENCES episodes(id);")
                except sqlite3.OperationalError:
                    pass
            conn.execute("CREATE INDEX IF NOT EXISTS idx_captures_episode ON captures(episode_id);")

            if "file_path" not in cols:
                try:
                    conn.execute("ALTER TABLE captures ADD COLUMN file_path TEXT;")
                except sqlite3.OperationalError:
                    pass
            conn.execute("CREATE INDEX IF NOT EXISTS idx_captures_file_path ON captures(file_path);")

            # Setup FTS5 full-text search table if supported
            if self.enable_fts:
                try:
                    conn.execute("""
                        CREATE VIRTUAL TABLE IF NOT EXISTS captures_fts USING fts5(
                            app_name,
                            window_title,
                            url,
                            ocr_text,
                            content='captures',
                            content_rowid='id'
                        );
                    """)

                    # Triggers to keep FTS index synchronized with main table
                    conn.execute("""
                        CREATE TRIGGER IF NOT EXISTS captures_ai AFTER INSERT ON captures BEGIN
                            INSERT INTO captures_fts(rowid, app_name, window_title, url, ocr_text)
                            VALUES (new.id, new.app_name, new.window_title, new.url, new.ocr_text);
                        END;
                    """)

                    conn.execute("""
                        CREATE TRIGGER IF NOT EXISTS captures_ad AFTER DELETE ON captures BEGIN
                            INSERT INTO captures_fts(captures_fts, rowid, app_name, window_title, url, ocr_text)
                            VALUES ('delete', old.id, old.app_name, old.window_title, old.url, old.ocr_text);
                        END;
                    """)

                    conn.execute("""
                        CREATE TRIGGER IF NOT EXISTS captures_au AFTER UPDATE ON captures BEGIN
                            INSERT INTO captures_fts(captures_fts, rowid, app_name, window_title, url, ocr_text)
                            VALUES ('delete', old.id, old.app_name, old.window_title, old.url, old.ocr_text);
                            INSERT INTO captures_fts(rowid, app_name, window_title, url, ocr_text)
                            VALUES (new.id, new.app_name, new.window_title, new.url, new.ocr_text);
                        END;
                    """)

                    # Setup windows_fts for Per-Window FTS search
                    conn.execute("""
                        CREATE VIRTUAL TABLE IF NOT EXISTS windows_fts USING fts5(
                            app_name,
                            title,
                            url,
                            ocr_text,
                            content='windows',
                            content_rowid='id'
                        );
                    """)
                    conn.execute("""
                        CREATE TRIGGER IF NOT EXISTS windows_ai AFTER INSERT ON windows BEGIN
                            INSERT INTO windows_fts(rowid, app_name, title, url, ocr_text)
                            VALUES (new.id, new.app_name, new.title, new.url, new.ocr_text);
                        END;
                    """)
                    conn.execute("""
                        CREATE TRIGGER IF NOT EXISTS windows_ad AFTER DELETE ON windows BEGIN
                            INSERT INTO windows_fts(windows_fts, rowid, app_name, title, url, ocr_text)
                            VALUES ('delete', old.id, old.app_name, old.title, old.url, old.ocr_text);
                        END;
                    """)
                    conn.execute("""
                        CREATE TRIGGER IF NOT EXISTS windows_au AFTER UPDATE ON windows BEGIN
                            INSERT INTO windows_fts(windows_fts, rowid, app_name, title, url, ocr_text)
                            VALUES ('delete', old.id, old.app_name, old.title, old.url, old.ocr_text);
                            INSERT INTO windows_fts(rowid, app_name, title, url, ocr_text)
                            VALUES (new.id, new.app_name, new.title, new.url, new.ocr_text);
                        END;
                    """)
                    logger.info("SQLite database and FTS5 full-text index initialized at %s", self.db_path)
                except Exception as e:
                    logger.warning("FTS5 table initialization failed (%s); full-text search will use LIKE fallback.", e)
                    self.enable_fts = False

            # Auto-backfill existing unclustered captures if upgrading
            try:
                ep_count = conn.execute("SELECT COUNT(*) FROM episodes;").fetchone()[0]
                cap_count = conn.execute("SELECT COUNT(*) FROM captures;").fetchone()[0]
                if ep_count == 0 and cap_count > 0:
                    self._backfill_episodes_internal(conn)
            except Exception as e:
                logger.debug("Episode auto-backfill skipped: %s", e)

    def save_capture(self, record: CaptureRecord, cluster_episode: bool = True) -> int:
        """Insert a capture record into SQLite and cluster into an episode. Returns new row id."""
        if not record.timestamp:
            record.timestamp = datetime.now(timezone.utc).isoformat()

        meta_json = json.dumps(record.metadata) if record.metadata else None

        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO captures (
                    timestamp, app_name, window_title, url, ocr_text,
                    screenshot_path, phash, width, height, is_redacted, metadata, episode_id, file_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.timestamp,
                    record.app_name,
                    record.window_title,
                    record.url,
                    record.ocr_text,
                    record.screenshot_path,
                    record.phash,
                    record.width,
                    record.height,
                    record.is_redacted,
                    meta_json,
                    record.episode_id,
                    record.file_path,
                ),
            )
            record.id = cursor.lastrowid

            if cluster_episode:
                try:
                    ep_id = self.cluster_or_create_episode(record, conn=conn)
                    record.episode_id = ep_id
                    conn.execute("UPDATE captures SET episode_id = ? WHERE id = ?;", (ep_id, record.id))
                except Exception as e:
                    logger.debug("Clustering capture into episode failed: %s", e)

            conn.commit()
            return record.id

    def update_capture(self, record_id: int, record: CaptureRecord) -> bool:
        """
        Update an existing capture record in SQLite.
        Triggers FTS5 synchronization automatically via captures_au.
        """
        meta_json = json.dumps(record.metadata) if record.metadata else None
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE captures SET
                    timestamp = ?,
                    app_name = ?,
                    window_title = ?,
                    url = ?,
                    ocr_text = ?,
                    screenshot_path = ?,
                    phash = ?,
                    width = ?,
                    height = ?,
                    is_redacted = ?,
                    metadata = ?,
                    file_path = ?
                WHERE id = ?;
                """,
                (
                    record.timestamp,
                    record.app_name,
                    record.window_title,
                    record.url,
                    record.ocr_text,
                    record.screenshot_path,
                    record.phash,
                    record.width,
                    record.height,
                    record.is_redacted,
                    meta_json,
                    record.file_path,
                    record_id,
                ),
            )
            conn.commit()
            return True

    def search(
        self,
        query: str = "",
        limit: int = 20,
        since: Optional[str] = None,
        until: Optional[str] = None,
        app_name: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> List[CaptureRecord]:
        """
        Search memory for keywords in app_name, window_title, url, file_path, or OCR text.
        Supports time bounding (since/until), application filtering (app_name), and file path filtering
        accelerated by composite B-Tree indexes.
        Uses FTS5 ranking when available, falling back to LIKE.
        """
        results: List[CaptureRecord] = []
        clean_query = query.strip() if query else ""

        with self.connection() as conn:
            # 1. If no search keyword, execute direct indexed query with filters
            if not clean_query:
                where_clauses = []
                params: List[Any] = []
                if since:
                    where_clauses.append("timestamp >= ?")
                    params.append(since)
                if until:
                    where_clauses.append("timestamp <= ?")
                    params.append(until)
                if app_name:
                    where_clauses.append("app_name LIKE ?")
                    params.append(f"%{app_name}%")
                if file_path:
                    where_clauses.append("file_path LIKE ?")
                    params.append(f"%{file_path}%")

                where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
                sql = f"SELECT * FROM captures {where_sql} ORDER BY timestamp DESC LIMIT ?;"
                params.append(limit)
                for row in conn.execute(sql, params):
                    results.append(self._row_to_record(row))
                return results

            # 2. FTS5 query with time & app filters
            if self.enable_fts:
                try:
                    safe_query = f'"{clean_query}"' if not any(c in clean_query for c in '*":') else clean_query
                    where_clauses = ["captures_fts MATCH ?"]
                    params = [safe_query]

                    if since:
                        where_clauses.append("c.timestamp >= ?")
                        params.append(since)
                    if until:
                        where_clauses.append("c.timestamp <= ?")
                        params.append(until)
                    if app_name:
                        where_clauses.append("c.app_name LIKE ?")
                        params.append(f"%{app_name}%")
                    if file_path:
                        where_clauses.append("c.file_path LIKE ?")
                        params.append(f"%{file_path}%")

                    where_sql = " AND ".join(where_clauses)
                    sql = f"""
                        SELECT c.* FROM captures c
                        JOIN captures_fts f ON c.id = f.rowid
                        WHERE {where_sql}
                        ORDER BY rank
                        LIMIT ?;
                    """
                    params.append(limit)
                    for row in conn.execute(sql, params):
                        results.append(self._row_to_record(row))
                    return results
                except sqlite3.OperationalError as e:
                    logger.debug("FTS5 search query error (%s); falling back to LIKE query.", e)

            # 3. Fallback LIKE query with time & app filters
            pattern = f"%{clean_query}%"
            where_clauses = [
                "(c.app_name LIKE ? OR c.window_title LIKE ? OR c.url LIKE ? OR c.ocr_text LIKE ? OR (c.file_path IS NOT NULL AND c.file_path LIKE ?))"
            ]
            params = [pattern, pattern, pattern, pattern, pattern]
            if since:
                where_clauses.append("c.timestamp >= ?")
                params.append(since)
            if until:
                where_clauses.append("c.timestamp <= ?")
                params.append(until)
            if app_name:
                where_clauses.append("c.app_name LIKE ?")
                params.append(f"%{app_name}%")
            if file_path:
                where_clauses.append("c.file_path LIKE ?")
                params.append(f"%{file_path}%")

            where_sql = " AND ".join(where_clauses)
            sql = f"""
                SELECT c.* FROM captures c
                WHERE {where_sql}
                ORDER BY c.timestamp DESC
                LIMIT ?;
            """
            params.append(limit)
            for row in conn.execute(sql, params):
                results.append(self._row_to_record(row))

        return results

    def get_recent(self, limit: int = 20) -> List[CaptureRecord]:
        """Retrieve most recent captures ordered by timestamp DESC."""
        results: List[CaptureRecord] = []
        with self.connection() as conn:
            sql = "SELECT * FROM captures ORDER BY id DESC LIMIT ?;"
            for row in conn.execute(sql, (limit,)):
                results.append(self._row_to_record(row))
        return results

    def get_by_id(self, capture_id: int) -> Optional[CaptureRecord]:
        """Retrieve a specific capture by its ID."""
        with self.connection() as conn:
            cursor = conn.execute("SELECT * FROM captures WHERE id = ?;", (capture_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_record(row)
        return None

    def save_windows(self, windows: List[WindowRecord]) -> List[int]:
        """Saves a batch of window records linked to a capture."""
        if not windows:
            return []
        ids = []
        with self.connection() as conn:
            for w in windows:
                cursor = conn.execute(
                    """
                    INSERT INTO windows (
                        capture_id, hwnd, app_name, pid, title, url,
                        rect_x, rect_y, rect_w, rect_h, z_index, is_foreground,
                        monitor, visible_fraction, ocr_text, ocr_lines,
                        text_hash, crop_path, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        w.capture_id,
                        w.hwnd,
                        w.app_name,
                        w.pid,
                        w.title,
                        w.url,
                        w.rect_x,
                        w.rect_y,
                        w.rect_w,
                        w.rect_h,
                        w.z_index,
                        int(w.is_foreground),
                        w.monitor,
                        w.visible_fraction,
                        w.ocr_text,
                        w.ocr_lines if isinstance(w.ocr_lines, str) else json.dumps(w.ocr_lines) if w.ocr_lines else None,
                        w.text_hash,
                        w.crop_path,
                        w.created_at or datetime.now(timezone.utc).isoformat(),
                    ),
                )
                w.id = cursor.lastrowid
                ids.append(w.id)
            conn.commit()
        return ids

    def get_windows_by_capture_id(self, capture_id: int) -> List[WindowRecord]:
        """Returns all visible windows recorded for a capture, ordered by z_index."""
        records = []
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM windows WHERE capture_id = ? ORDER BY z_index ASC;",
                (capture_id,)
            )
            for row in cursor:
                records.append(self._row_to_window_record(row))
        return records

    def get_window_by_id(self, window_id: int) -> Optional[WindowRecord]:
        """Returns a single window record by its primary key ID."""
        with self.connection() as conn:
            cursor = conn.execute("SELECT * FROM windows WHERE id = ?;", (window_id,))
            row = cursor.fetchone()
            return self._row_to_window_record(row) if row else None

    def get_window_count(self) -> int:
        """Returns total number of window records stored."""
        with self.connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM windows;")
            row = cursor.fetchone()
            return row[0] if row else 0

    def _row_to_window_record(self, row: sqlite3.Row) -> WindowRecord:
        return WindowRecord(
            id=row["id"],
            capture_id=row["capture_id"],
            hwnd=row["hwnd"],
            app_name=row["app_name"],
            pid=row["pid"],
            title=row["title"],
            url=row["url"],
            rect_x=row["rect_x"],
            rect_y=row["rect_y"],
            rect_w=row["rect_w"],
            rect_h=row["rect_h"],
            z_index=row["z_index"],
            is_foreground=row["is_foreground"],
            monitor=row["monitor"],
            visible_fraction=row["visible_fraction"],
            ocr_text=row["ocr_text"] or "",
            ocr_lines=row["ocr_lines"],
            text_hash=row["text_hash"],
            crop_path=row["crop_path"],
            created_at=row["created_at"] or "",
        )

    def get_stats(self) -> Dict[str, Any]:
        """Return memory storage statistics."""
        with self.connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM captures;").fetchone()[0]
            total_windows = conn.execute("SELECT COUNT(*) FROM windows;").fetchone()[0]
            redacted = conn.execute("SELECT COUNT(*) FROM captures WHERE is_redacted = 1;").fetchone()[0]
            first_ts = conn.execute("SELECT MIN(timestamp) FROM captures;").fetchone()[0]
            last_ts = conn.execute("SELECT MAX(timestamp) FROM captures;").fetchone()[0]

            db_size_bytes = os.path.getsize(self.db_path) if self.db_path.is_file() else 0

            return {
                "total_captures": total,
                "total_windows": total_windows,
                "redacted_captures": redacted,
                "first_capture_timestamp": first_ts,
                "last_capture_timestamp": last_ts,
                "database_size_bytes": db_size_bytes,
                "database_size_mb": round(db_size_bytes / (1024 * 1024), 2),
            }

    def cleanup_old_records(self, retention_days: int = 30) -> int:
        """Delete records older than retention_days and their screenshot files."""
        if retention_days <= 0:
            return 0

        cutoff = datetime.now(timezone.utc).timestamp() - (retention_days * 86400)
        cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()

        deleted_count = 0
        with self.connection() as conn:
            # Query screenshot paths to delete
            rows = conn.execute(
                "SELECT id, screenshot_path FROM captures WHERE timestamp < ?;",
                (cutoff_iso,)
            ).fetchall()

            for row in rows:
                path_str = row["screenshot_path"]
                if path_str:
                    try:
                        p = Path(path_str)
                        if p.is_file():
                            p.unlink(missing_ok=True)
                    except Exception:
                        pass

            cursor = conn.execute("DELETE FROM captures WHERE timestamp < ?;", (cutoff_iso,))
            deleted_count = cursor.rowcount
            conn.commit()

        logger.info("Cleaned up %d captures older than %d days.", deleted_count, retention_days)
        return deleted_count

    def sanitize_database(self, privacy_gate: Optional[Any] = None) -> Dict[str, Any]:
        """
        Retroactively scans all captures in the SQLite database and sanitizes
        plaintext API keys, tokens, credentials, and blocked window titles.
        Updates captures and synchronizes FTS5 full-text index automatically.
        """
        if privacy_gate is None:
            from memvision.privacy import PrivacyGatekeeper
            privacy_gate = PrivacyGatekeeper()

        updated_count = 0
        total_tokens_redacted = 0
        total_scanned = 0

        with self.connection() as conn:
            rows = conn.execute("SELECT id, app_name, window_title, url, ocr_text, is_redacted, metadata FROM captures;").fetchall()
            total_scanned = len(rows)

            for row in rows:
                rec_id = row["id"]
                app = row["app_name"] or ""
                title = row["window_title"] or ""
                url = row["url"] or ""
                ocr = row["ocr_text"] or ""
                curr_redacted = row["is_redacted"]
                meta = {}
                if row["metadata"]:
                    try:
                        meta = json.loads(row["metadata"])
                    except Exception:
                        meta = {}

                # 1. Check if window title matches blocked titles (e.g. *omniroute*, *combo*.txt)
                decision = privacy_gate.evaluate(app_name=app, window_title=title, url=url)
                title_blocked = not decision.is_allowed

                # 2. Redact text and URL secrets
                sanitized_ocr, ocr_count, ocr_rules = privacy_gate.redact_text(ocr)
                sanitized_title, title_count, title_rules = privacy_gate.redact_text(title)
                sanitized_url, url_count, url_rules = (
                    privacy_gate.redact_url(url) if hasattr(privacy_gate, "redact_url") else (url, 0, [])
                )

                row_redactions = ocr_count + title_count + url_count
                should_update = False

                if title_blocked and "[REDACTED BY PRIVACY RULE" not in sanitized_ocr:
                    # If window title is a blocked secret file, purge its OCR completely!
                    sanitized_ocr = f"[REDACTED BY PRIVACY RULE: {decision.reason}]"
                    sanitized_title = f"[REDACTED_FILE: {decision.matched_rule}]"
                    row_redactions += 1
                    should_update = True

                if (
                    row_redactions > 0
                    or sanitized_ocr != ocr
                    or sanitized_title != title
                    or sanitized_url != url
                    or (title_blocked and curr_redacted != 1)
                ):
                    should_update = True

                if should_update:
                    total_tokens_redacted += row_redactions
                    updated_count += 1
                    meta["content_redacted_count"] = meta.get("content_redacted_count", 0) + row_redactions
                    meta["retroactive_sanitized"] = True

                    conn.execute(
                        """
                        UPDATE captures
                        SET window_title = ?,
                            url = ?,
                            ocr_text = ?,
                            is_redacted = 1,
                            metadata = ?
                        WHERE id = ?;
                        """,
                        (sanitized_title, sanitized_url, sanitized_ocr, json.dumps(meta), rec_id)
                    )

            conn.commit()

        logger.info(
            "Retroactive sanitization complete: scanned %d captures, sanitized %d records (%d tokens redacted).",
            total_scanned, updated_count, total_tokens_redacted
        )
        return {
            "total_scanned": total_scanned,
            "records_sanitized": updated_count,
            "tokens_redacted": total_tokens_redacted,
        }

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> CaptureRecord:
        meta = None
        if row["metadata"]:
            try:
                meta = json.loads(row["metadata"])
            except Exception:
                meta = None

        ep_id = row["episode_id"] if "episode_id" in row.keys() else None
        fp = row["file_path"] if "file_path" in row.keys() else None
        if not fp and meta:
            fp = meta.get("file_path")

        return CaptureRecord(
            id=row["id"],
            timestamp=row["timestamp"],
            app_name=row["app_name"],
            window_title=row["window_title"] or "",
            url=row["url"],
            ocr_text=row["ocr_text"] or "",
            screenshot_path=row["screenshot_path"],
            phash=row["phash"] or "",
            width=row["width"] or 0,
            height=row["height"] or 0,
            is_redacted=row["is_redacted"] or 0,
            metadata=meta,
            episode_id=ep_id,
            file_path=fp,
        )

    def cluster_or_create_episode(
        self,
        record: CaptureRecord,
        max_gap_seconds: int = 180,
        conn: Optional[sqlite3.Connection] = None,
    ) -> int:
        """
        Groups the capture into an active Episode (Task Session) or creates a new one.
        A frame continues an episode if:
          1. Same app_name.
          2. Time since last frame <= max_gap_seconds.
        """
        def _do_cluster(c: sqlite3.Connection) -> int:
            row = c.execute(
                "SELECT * FROM episodes ORDER BY id DESC LIMIT 1;"
            ).fetchone()

            rec_time = datetime.fromisoformat(record.timestamp) if record.timestamp else datetime.now(timezone.utc)

            if row:
                last_ep_id = row["id"]
                last_app = row["app_name"]
                last_end = row["end_time"]
                last_start = row["start_time"]
                last_count = row["capture_count"]

                try:
                    last_end_dt = datetime.fromisoformat(last_end)
                    gap_seconds = (rec_time - last_end_dt).total_seconds()
                except Exception:
                    gap_seconds = 999999

                # Check if same application and within gap threshold
                if last_app.lower() == (record.app_name or "").lower() and 0 <= gap_seconds <= max_gap_seconds:
                    try:
                        start_dt = datetime.fromisoformat(last_start)
                        duration = max(0, int((rec_time - start_dt).total_seconds()))
                    except Exception:
                        duration = 0

                    current_kw = row["summary_keywords"] or ""
                    new_kw = self._extract_session_keywords(record.window_title, record.url)
                    combined_kw = self._merge_keywords(current_kw, new_kw)
                    ep_url = row["url"] or record.url

                    c.execute(
                        """
                        UPDATE episodes
                        SET end_time = ?,
                            duration_seconds = ?,
                            capture_count = ?,
                            url = ?,
                            summary_keywords = ?
                        WHERE id = ?;
                        """,
                        (record.timestamp, duration, last_count + 1, ep_url, combined_kw, last_ep_id),
                    )
                    return last_ep_id

            # Create new episode
            kw = self._extract_session_keywords(record.window_title, record.url)
            cursor = c.execute(
                """
                INSERT INTO episodes (
                    app_name, title, url, start_time, end_time,
                    duration_seconds, capture_count, key_capture_id,
                    screenshot_path, summary_keywords
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    record.app_name,
                    record.window_title,
                    record.url,
                    record.timestamp,
                    record.timestamp,
                    0,
                    1,
                    record.id,
                    record.screenshot_path,
                    kw,
                ),
            )
            return cursor.lastrowid

        if conn is not None:
            return _do_cluster(conn)
        else:
            with self.connection() as c:
                ep_id = _do_cluster(c)
                c.commit()
                return ep_id

    def get_episodes(self, limit: int = 20) -> List[EpisodeRecord]:
        """Retrieve recent task/focus episodes ordered by start_time DESC."""
        results: List[EpisodeRecord] = []
        with self.connection() as conn:
            sql = "SELECT * FROM episodes ORDER BY id DESC LIMIT ?;"
            for row in conn.execute(sql, (limit,)):
                results.append(self._row_to_episode(row))
        return results

    def search_episodes(self, query: str = "", limit: int = 10) -> List[EpisodeRecord]:
        """Search episodes by application, title, URL, or keywords."""
        results: List[EpisodeRecord] = []
        clean = query.strip()
        if not clean:
            return self.get_episodes(limit=limit)

        pattern = f"%{clean}%"
        with self.connection() as conn:
            sql = """
                SELECT * FROM episodes
                WHERE app_name LIKE ?
                   OR title LIKE ?
                   OR url LIKE ?
                   OR summary_keywords LIKE ?
                ORDER BY id DESC
                LIMIT ?;
            """
            for row in conn.execute(sql, (pattern, pattern, pattern, pattern, limit)):
                results.append(self._row_to_episode(row))
        return results

    def _backfill_episodes_internal(self, conn: sqlite3.Connection) -> int:
        """Internal helper to cluster existing unclustered captures in chronological order."""
        rows = conn.execute("SELECT * FROM captures ORDER BY id ASC;").fetchall()
        if not rows:
            return 0

        created = 0
        for row in rows:
            rec = self._row_to_record(row)
            ep_id = self.cluster_or_create_episode(rec, conn=conn)
            conn.execute("UPDATE captures SET episode_id = ? WHERE id = ?;", (ep_id, rec.id))
            created += 1

        conn.commit()
        logger.info("Successfully clustered %d existing captures into episodes.", created)
        return created

    @staticmethod
    def _extract_session_keywords(title: Optional[str], url: Optional[str]) -> str:
        """Extracts clean informative keywords for an episode."""
        words = []
        if title:
            cleaned = re.sub(r"[^\w\s.-]", " ", title)
            words.extend([w for w in cleaned.split() if len(w) >= 3][:8])
        if url:
            try:
                parsed = urlparse(url)
                if parsed.netloc:
                    words.append(parsed.netloc)
            except Exception:
                pass
        return " ".join(dict.fromkeys(words))

    @staticmethod
    def _merge_keywords(existing: str, new_kw: str) -> str:
        combined = (existing + " " + new_kw).split()
        unique = list(dict.fromkeys(combined))[:20]
        return " ".join(unique)

    @staticmethod
    def _row_to_episode(row: sqlite3.Row) -> EpisodeRecord:
        return EpisodeRecord(
            id=row["id"],
            app_name=row["app_name"],
            title=row["title"] or "",
            url=row["url"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            duration_seconds=row["duration_seconds"] or 0,
            capture_count=row["capture_count"] or 1,
            key_capture_id=row["key_capture_id"],
            screenshot_path=row["screenshot_path"],
            summary_keywords=row["summary_keywords"] or "",
        )
