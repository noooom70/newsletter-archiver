"""Tidy command - mark previously archived newsletters read + archived in the mailbox."""

import typer
from rich import print as rprint
from rich.progress import BarColumn, Progress, TextColumn

from newsletter_archiver.core.config import get_settings
from newsletter_archiver.core.exceptions import AuthError, FetchError
from newsletter_archiver.fetcher.graph_client import GraphClient
from newsletter_archiver.fetcher.tidy import tidy_newsletter
from newsletter_archiver.storage.db_manager import DatabaseManager


def app(
    dry_run: bool = typer.Option(False, "--dry-run", help="Only report how many emails would be tidied"),
):
    """Mark already-archived newsletters as read and move them to the Archive folder.

    Sweeps every archived newsletter that hasn't been tidied yet. Safe to
    re-run: completed newsletters are skipped, and emails that no longer
    exist in the mailbox are marked done.
    """
    settings = get_settings()
    settings.ensure_dirs()
    db = DatabaseManager()

    untidied = db.get_untidied_newsletters()
    if not untidied:
        rprint("[green]Nothing to tidy — all archived newsletters are marked done.[/green]")
        return
    rprint(f"[bold]{len(untidied)}[/bold] archived newsletter(s) not yet tidied in the mailbox.")
    if dry_run:
        return

    graph = GraphClient()
    try:
        graph.authenticate()
    except AuthError as e:
        rprint(f"[red]Authentication failed:[/red] {e}")
        raise typer.Exit(1)

    tidied = 0
    gone = 0
    failed = 0

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
    ) as progress:
        task = progress.add_task("Tidying mailbox...", total=len(untidied))

        for nl in untidied:
            try:
                message = graph.get_message(nl.message_id)
            except FetchError:
                failed += 1
                progress.advance(task)
                continue

            if message is None:
                # Deleted or moved (moves change message IDs): nothing to do
                db.mark_newsletter_tidied(nl.id)
                gone += 1
                progress.advance(task)
                continue

            internet_message_id = message.get("internetMessageId", "")
            if tidy_newsletter(
                graph, db, nl.id, nl.message_id,
                internet_message_id=internet_message_id,
            ):
                tidied += 1
            else:
                failed += 1
            progress.advance(task)

    rprint()
    rprint("[green]✓[/green] Done!")
    rprint(f"  Marked read + archived: [bold green]{tidied}[/bold green]")
    if gone:
        rprint(f"  No longer in mailbox (marked done): [dim]{gone}[/dim]")
    if failed:
        rprint(f"  Failed (will retry on next run): [yellow]{failed}[/yellow]")
