"""Search command - keyword, semantic, and RAG Q&A search over archived newsletters."""

from typing import Optional

import typer
from rich.console import Console
from rich import print as rprint
from rich.table import Table

from newsletter_archiver.core.config import get_settings

app = typer.Typer(no_args_is_help=True)


@app.command()
def keyword(
    query: str = typer.Argument(help="Search query (supports FTS5 syntax: phrases, AND, OR, NOT)"),
    limit: int = typer.Option(20, "--limit", "-n", help="Maximum results to return"),
    sender: Optional[str] = typer.Option(None, "--sender", "-s", help="Filter by sender name"),
):
    """Search newsletters by keyword using full-text search."""
    settings = get_settings()
    settings.ensure_dirs()

    from newsletter_archiver.search.fts import FTSManager
    from newsletter_archiver.storage.db_manager import DatabaseManager

    fts = FTSManager(settings.db_path)
    fts.ensure_table()
    db = DatabaseManager()

    results = fts.search(query, limit=limit, sender=sender)

    if not results:
        rprint(f"[yellow]No results for:[/yellow] {query}")
        return

    table = Table(title=f"Results for: {query}", show_lines=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Date", width=10)
    table.add_column("Subject", style="bold", max_width=50)
    table.add_column("Sender", max_width=25)
    table.add_column("Snippet", max_width=60)

    for i, r in enumerate(results, 1):
        # Format snippet: highlight matches between >>> and <<<
        snippet = r.snippet.replace(">>>", "[bold yellow]").replace("<<<", "[/bold yellow]")
        nl = db.get_newsletter_by_id(r.newsletter_id)
        date_str = nl.received_date.strftime("%Y-%m-%d") if nl and nl.received_date else ""
        table.add_row(str(i), date_str, r.subject, r.sender_name, snippet)

    rprint(table)
    rprint(f"\n[dim]{len(results)} result(s)[/dim]")


@app.command()
def ask(
    query: str = typer.Argument(help="Question to answer using your newsletter archive"),
    limit: int = typer.Option(10, "--limit", "-n", help="Number of chunks to retrieve"),
    sender: Optional[str] = typer.Option(None, "--sender", "-s", help="Filter by sender name"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Override Claude model"),
):
    """Ask a question and get an AI-generated answer grounded in your archive."""
    settings = get_settings()
    settings.ensure_dirs()

    from newsletter_archiver.search.rag import ask as rag_ask
    from newsletter_archiver.storage.db_manager import DatabaseManager

    console = Console()
    db = DatabaseManager()

    console.print("[dim]Searching archive and generating answer...[/dim]\n")

    try:
        result = rag_ask(query, db, top_k=limit, sender=sender, model=model)
    except RuntimeError as e:
        rprint(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if result.stream is None:
        rprint("[yellow]No relevant content found in the archive.[/yellow]")
        return

    # Stream the response
    for chunk in result.stream:
        console.print(chunk, end="", highlight=False)
    console.print()  # final newline

    # Print sources
    if result.sources:
        console.print("\n[bold]Sources:[/bold]")
        for src in result.sources:
            console.print(f"  - {src['subject']} — {src['sender_name']} ({src['date']})")

@app.command()
def semantic(
    query: str = typer.Argument(help="Natural language search query"),
    limit: int = typer.Option(10, "--limit", "-n", help="Maximum results to return"),
    sender: Optional[str] = typer.Option(None, "--sender", "-s", help="Filter by sender name"),
):
    """Search newsletters by meaning using vector similarity."""
    settings = get_settings()
    settings.ensure_dirs()

    from newsletter_archiver.search.vector import VectorSearchManager
    from newsletter_archiver.storage.db_manager import DatabaseManager

    rprint("[dim]Loading search model...[/dim]")
    vm = VectorSearchManager()
    db = DatabaseManager()

    results = vm.search(query, db, top_k=limit, sender=sender)

    if not results:
        rprint(f"[yellow]No results for:[/yellow] {query}")
        return

    table = Table(title=f"Semantic results for: {query}", show_lines=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Date", width=10)
    table.add_column("Subject", style="bold", max_width=50)
    table.add_column("Sender", max_width=25)
    table.add_column("Score", width=6)
    table.add_column("Snippet", max_width=60)

    for i, r in enumerate(results, 1):
        table.add_row(str(i), r.date, r.subject, r.sender_name, f"{r.score:.3f}", r.snippet)

    rprint(table)
    rprint(f"\n[dim]{len(results)} result(s)[/dim]")
