"""İndirilen haberlerin SQLite kaydı — mükerrer indirmeyi önler, checkpoint tutar."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path


class SeenStore:
    def __init__(self, db_path: str):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen (
                agency    TEXT NOT NULL,
                news_id   TEXT NOT NULL,
                seen_at   TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (agency, news_id)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS checkpoint (
                agency  TEXT NOT NULL,
                key     TEXT NOT NULL,
                value   TEXT,
                PRIMARY KEY (agency, key)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pending (
                agency   TEXT NOT NULL,
                news_id  TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (agency, news_id)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS failures (
                agency    TEXT NOT NULL,
                news_id   TEXT NOT NULL,
                title     TEXT,
                reason    TEXT,
                failed_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (agency, news_id)
            )
            """
        )
        self._conn.commit()

    def bump_attempt(self, agency: str, news_id: str) -> int:
        with self._lock:
            self._conn.execute(
                "INSERT INTO pending (agency, news_id, attempts) VALUES (?, ?, 1) "
                "ON CONFLICT(agency, news_id) DO UPDATE SET attempts = attempts + 1",
                (agency, str(news_id)),
            )
            self._conn.commit()
            cur = self._conn.execute(
                "SELECT attempts FROM pending WHERE agency=? AND news_id=?", (agency, str(news_id))
            )
            return int(cur.fetchone()[0])

    def clear_pending(self, agency: str, news_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM pending WHERE agency=? AND news_id=?", (agency, str(news_id))
            )
            self._conn.commit()

    def record_failure(self, agency: str, news_id: str, title: str, reason: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO failures (agency, news_id, title, reason) VALUES (?, ?, ?, ?)",
                (agency, str(news_id), title, reason),
            )
            self._conn.commit()

    def failure_count(self, agency: str | None = None) -> int:
        with self._lock:
            if agency:
                cur = self._conn.execute("SELECT COUNT(*) FROM failures WHERE agency=?", (agency,))
            else:
                cur = self._conn.execute("SELECT COUNT(*) FROM failures")
            return int(cur.fetchone()[0])

    def recent_failures(self, n: int = 50) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT agency, news_id, title, reason, failed_at FROM failures "
                "ORDER BY failed_at DESC LIMIT ?", (n,)
            )
            return [dict(agency=r[0], news_id=r[1], title=r[2], reason=r[3], failed_at=r[4])
                    for r in cur.fetchall()]

    def get_checkpoint(self, agency: str, key: str) -> str | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT value FROM checkpoint WHERE agency=? AND key=?", (agency, key)
            )
            row = cur.fetchone()
            return row[0] if row else None

    def set_checkpoint(self, agency: str, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO checkpoint (agency, key, value) VALUES (?, ?, ?)",
                (agency, key, value),
            )
            self._conn.commit()

    def is_seen(self, agency: str, news_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "SELECT 1 FROM seen WHERE agency=? AND news_id=? LIMIT 1",
                (agency, str(news_id)),
            )
            return cur.fetchone() is not None

    def mark_seen(self, agency: str, news_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO seen (agency, news_id) VALUES (?, ?)",
                (agency, str(news_id)),
            )
            self._conn.commit()

    def count(self, agency: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "SELECT COUNT(*) FROM seen WHERE agency=?", (agency,)
            )
            return int(cur.fetchone()[0])

    def prune_old(self, days: int = 30) -> int:
        # en az 2 gün saklanır; çekim penceresindeki hiçbir kayıt silinmez
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM seen WHERE seen_at < datetime('now', ?)",
                (f"-{max(2, int(days))} days",),
            )
            self._conn.commit()
            return cur.rowcount

    def close(self) -> None:
        with self._lock:
            self._conn.close()
