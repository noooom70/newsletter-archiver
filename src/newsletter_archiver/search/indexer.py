"""Orchestrates FTS and vector search indexing."""

from pathlib import Path

from rich import print as rprint
from rich.progress import BarColumn, Progress, TextColumn

from newsletter_archiver.core.config import get_settings
from newsletter_archiver.search.chunker import clean_for_indexing
from newsletter_archiver.search.fts import FTSManager
from newsletter_archiver.storage.db_manager import DatabaseManager


class SearchIndexer:
    def __init__(self, db: DatabaseManager | None = None):
        self.db = db or DatabaseManager()
        settings = get_settings()
        self.fts = FTSManager(settings.db_path)
        self.fts.ensure_table()
        self._vector = None  # lazy-loaded

    @property
    def vector(self):
        """Lazy-load vector search manager to avoid importing sentence-transformers."""
        if self._vector is None:
            from newsletter_archiver.search.vector import VectorSearchManager
            self._vector = VectorSearchManager()
        return self._vector

    def _read_markdown(self, markdown_path: str) -> str | None:
        """Read markdown file content, returning None if not found."""
        path = Path(markdown_path)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def index_newsletter_fts(self, newsletter_id: int, subject: str,
                              sender_name: str, markdown_path: str) -> bool:
        """Index a single newsletter in FTS. Returns True on success."""
        content = self._read_markdown(markdown_path)
        if content is None:
            return False
        cleaned = clean_for_indexing(content)
        self.fts.index_newsletter(newsletter_id, subject, sender_name, cleaned)
        return True

    def index_newsletter_vector(self, newsletter_id: int, markdown_path: str) -> bool:
        """Index a single newsletter in vector store. Returns True on success."""
        content = self._read_markdown(markdown_path)
        if content is None:
            return False
        cleaned = clean_for_indexing(content)
        self.vector.index_newsletter(newsletter_id, cleaned, self.db)
        return True

    def index_newsletter(self, newsletter_id: int, subject: str,
                          sender_name: str, markdown_path: str,
                          fts: bool = True, vector: bool = True) -> None:
        """Index a single newsletter in both FTS and vector stores."""
        if fts:
            self.index_newsletter_fts(newsletter_id, subject, sender_name, markdown_path)
        if vector:
            self.index_newsletter_vector(newsletter_id, markdown_path)

    def index_all(self, reindex: bool = False, fts_only: bool = False,
                  vector_only: bool = False) -> tuple[int, int]:
        """Batch index all newsletters. Returns (fts_count, vector_count)."""
        newsletters = self.db.get_all_newsletters()
        if not newsletters:
            rprint("[yellow]No newsletters to index.[/yellow]")
            return (0, 0)

        do_fts = not vector_only
        do_vector = not fts_only

        if reindex and do_fts:
            self.fts.rebuild()
            self.fts.ensure_table()
        if reindex and do_vector:
            self.vector.clear()

        fts_indexed = set() if reindex else (self.fts.get_indexed_ids() if do_fts else set())
        vector_indexed = set() if reindex else (self.vector.get_indexed_ids(self.db) if do_vector else set())

        fts_count = 0
        vector_count = 0

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
        ) as progress:
            task = progress.add_task("Indexing newsletters...", total=len(newsletters))

            for nl in newsletters:
                if do_fts and nl.id not in fts_indexed:
                    if self.index_newsletter_fts(nl.id, nl.subject, nl.sender_name or "", nl.markdown_path):
                        fts_count += 1

                if do_vector and nl.id not in vector_indexed:
                    if self.index_newsletter_vector(nl.id, nl.markdown_path):
                        vector_count += 1

                progress.advance(task)

        if do_vector and vector_count > 0:
            self.vector.save()

        return (fts_count, vector_count)

    def index_missing(self) -> tuple[int, int]:
        """Only index newsletters not yet in either index."""
        return self.index_all(reindex=False)

    def get_status(self) -> dict:
        """Return indexing status counts."""
        total = self.db.get_newsletter_count()
        fts_count = len(self.fts.get_indexed_ids())
        return {
            "total_newsletters": total,
            "fts_indexed": fts_count,
        }
