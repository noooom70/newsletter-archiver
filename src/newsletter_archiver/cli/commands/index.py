"""Index command - build and manage search indexes."""

import typer
from rich import print as rprint

from newsletter_archiver.core.config import get_settings
from newsletter_archiver.storage.db_manager import DatabaseManager

app = typer.Typer(no_args_is_help=True)


@app.command()
def build(
    reindex: bool = typer.Option(False, "--reindex", help="Drop and rebuild indexes from scratch"),
    fts_only: bool = typer.Option(False, "--fts-only", help="Only build FTS keyword index"),
    vector_only: bool = typer.Option(False, "--vector-only", help="Only build vector embeddings index"),
):
    """Build or rebuild search indexes."""
    settings = get_settings()
    settings.ensure_dirs()

    from newsletter_archiver.search.indexer import SearchIndexer

    indexer = SearchIndexer()

    action = "Rebuilding" if reindex else "Building"
    scope = "FTS" if fts_only else ("vector" if vector_only else "FTS + vector")
    rprint(f"[bold]{action} {scope} index...[/bold]\n")

    fts_count, vector_count = indexer.index_all(
        reindex=reindex, fts_only=fts_only, vector_only=vector_only,
    )

    rprint()
    if not vector_only:
        rprint(f"  FTS indexed: [bold green]{fts_count}[/bold green] newsletters")
    if not fts_only:
        rprint(f"  Vector indexed: [bold green]{vector_count}[/bold green] newsletters")


@app.command()
def status():
    """Show search index status."""
    settings = get_settings()
    settings.ensure_dirs()

    from newsletter_archiver.search.indexer import SearchIndexer

    indexer = SearchIndexer()
    stats = indexer.get_status()

    rprint(f"  Total newsletters: [bold]{stats['total_newsletters']}[/bold]")
    rprint(f"  FTS indexed:       [bold]{stats['fts_indexed']}[/bold]")

    # Only show vector stats if embeddings exist (avoid loading sentence-transformers)
    try:
        from newsletter_archiver.search.vector import VectorSearchManager
        vm = VectorSearchManager()
        db = DatabaseManager()
        vector_count = len(vm.get_indexed_ids(db))
        rprint(f"  Vector indexed:    [bold]{vector_count}[/bold]")
    except Exception:
        rprint(f"  Vector indexed:    [dim]not available[/dim]")
