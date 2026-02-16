"""FTS5 full-text search manager using raw sqlite3 (FTS5 DDL not supported by SQLAlchemy)."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FTSResult:
    newsletter_id: int
    subject: str
    sender_name: str
    snippet: str
    rank: float


class FTSManager:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def ensure_table(self) -> None:
        """Create the FTS5 virtual table if it doesn't exist."""
        conn = self._connect()
        try:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS newsletters_fts USING fts5(
                    subject, content, sender_name,
                    newsletter_id UNINDEXED,
                    tokenize='porter unicode61'
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def index_newsletter(
        self, newsletter_id: int, subject: str, sender_name: str, content: str
    ) -> None:
        """Insert or replace a newsletter in the FTS index."""
        conn = self._connect()
        try:
            # Delete existing entry for this newsletter_id
            conn.execute(
                "DELETE FROM newsletters_fts WHERE newsletter_id = ?",
                (newsletter_id,),
            )
            conn.execute(
                "INSERT INTO newsletters_fts (subject, content, sender_name, newsletter_id) "
                "VALUES (?, ?, ?, ?)",
                (subject, content, sender_name, newsletter_id),
            )
            conn.commit()
        finally:
            conn.close()

    def search(self, query: str, limit: int = 20, sender: str | None = None) -> list[FTSResult]:
        """Search the FTS index. Returns results ranked by relevance."""
        conn = self._connect()
        try:
            if sender:
                rows = conn.execute(
                    """
                    SELECT newsletter_id, subject, sender_name,
                           snippet(newsletters_fts, 1, '>>>', '<<<', '...', 48) as snippet,
                           rank
                    FROM newsletters_fts
                    WHERE newsletters_fts MATCH ? AND sender_name LIKE ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (query, f"%{sender}%", limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT newsletter_id, subject, sender_name,
                           snippet(newsletters_fts, 1, '>>>', '<<<', '...', 48) as snippet,
                           rank
                    FROM newsletters_fts
                    WHERE newsletters_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (query, limit),
                ).fetchall()
            return [
                FTSResult(
                    newsletter_id=row[0],
                    subject=row[1],
                    sender_name=row[2],
                    snippet=row[3],
                    rank=row[4],
                )
                for row in rows
            ]
        finally:
            conn.close()

    def get_indexed_ids(self) -> set[int]:
        """Get the set of newsletter IDs currently in the FTS index."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT DISTINCT newsletter_id FROM newsletters_fts"
            ).fetchall()
            return {row[0] for row in rows}
        finally:
            conn.close()

    def rebuild(self) -> None:
        """Drop and recreate the FTS table."""
        conn = self._connect()
        try:
            conn.execute("DROP TABLE IF EXISTS newsletters_fts")
            conn.commit()
        finally:
            conn.close()
        self.ensure_table()
