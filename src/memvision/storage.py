"""
SQLite and FTS5 Storage Engine for mem-vision-mcp.
Provides high-performance persistent storage and instant full-text search over captured memory.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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

    def to_dict(self) -> dict:
        d = asdict(self)
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
                    logger.info("SQLite database and FTS5 full-text index initialized at %s", self.db_path)
                except Exception as e:
                    logger.warning("FTS5 table initialization failed (%s); full-text search will use LIKE fallback.", e)
                    self.enable_fts = False

    def save_capture(self, record: CaptureRecord) -> int:
        """Insert a capture record into SQLite. Returns new row id."""
        if not record.timestamp:
            record.timestamp = datetime.now(timezone.utc).isoformat()

        meta_json = json.dumps(record.metadata) if record.metadata else None

        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO captures (
                    timestamp, app_name, window_title, url, ocr_text,
                    screenshot_path, phash, width, height, is_redacted, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
            record.id = cursor.lastrowid
            conn.commit()
            return record.id

    def search(self, query: str, limit: int = 20) -> List[CaptureRecord]:
        """
        Search memory for keywords in app_name, window_title, url, or OCR text.
        Uses FTS5 ranking when available, falling back to LIKE.
        """
        results: List[CaptureRecord] = []
        if not query or not query.strip():
            return self.get_recent(limit=limit)

        clean_query = query.strip()

        with self.connection() as conn:
            if self.enable_fts:
                try:
                    # Sanitize FTS query for boolean tokens
                    safe_query = f'"{clean_query}"' if not any(c in clean_query for c in '*":') else clean_query
                    sql = """
                        SELECT c.* FROM captures c
                        JOIN captures_fts f ON c.id = f.rowid
                        WHERE captures_fts MATCH ?
                        ORDER BY rank
                        LIMIT ?;
                    """
                    for row in conn.execute(sql, (safe_query, limit)):
                        results.append(self._row_to_record(row))
                    return results
                except sqlite3.OperationalError as e:
                    logger.debug("FTS5 search query error (%s); falling back to LIKE query.", e)

            # Fallback LIKE query
            sql = """
                SELECT * FROM captures
                WHERE app_name LIKE ?
                   OR window_title LIKE ?
                   OR url LIKE ?
                   OR ocr_text LIKE ?
                ORDER BY id DESC
                LIMIT ?;
            """
            pattern = f"%{clean_query}%"
            for row in conn.execute(sql, (pattern, pattern, pattern, pattern, limit)):
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

    def get_stats(self) -> Dict[str, Any]:
        """Return memory storage statistics."""
        with self.connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM captures;").fetchone()[0]
            redacted = conn.execute("SELECT COUNT(*) FROM captures WHERE is_redacted = 1;").fetchone()[0]
            first_ts = conn.execute("SELECT MIN(timestamp) FROM captures;").fetchone()[0]
            last_ts = conn.execute("SELECT MAX(timestamp) FROM captures;").fetchone()[0]

            db_size_bytes = os.path.getsize(self.db_path) if self.db_path.is_file() else 0

            return {
                "total_captures": total,
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

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> CaptureRecord:
        meta = None
        if row["metadata"]:
            try:
                meta = json.loads(row["metadata"])
            except Exception:
                meta = None

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
        )
