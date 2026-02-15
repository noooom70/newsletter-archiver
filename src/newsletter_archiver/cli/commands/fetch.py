"""Fetch command - download newsletters from Outlook."""

from typing import Optional

import typer
from rich import print as rprint
from rich.progress import Progress, SpinnerColumn, TextColumn

from newsletter_archiver.core.config import get_settings
from newsletter_archiver.core.exceptions import AuthError, FetchError
from newsletter_archiver.fetcher.content_extractor import (
    build_markdown_document,
    calculate_reading_time,
    calculate_word_count,
    html_to_markdown,
)
from newsletter_archiver.fetcher.email_parser import parse_message
from newsletter_archiver.fetcher.graph_client import GraphClient
from newsletter_archiver.storage.db_manager import DatabaseManager
from newsletter_archiver.storage.file_manager import (
    get_archive_path,
    save_newsletter_files,
)


def app(
    days_back: int = typer.Option(7, "--days-back", "-d", help="Number of days back to fetch"),
    sender: Optional[str] = typer.Option(None, "--sender", "-s", help="Filter by sender email or domain"),
    all_mail: bool = typer.Option(False, "--all", help="Fetch all emails, not just detected newsletters"),
):
    """Fetch newsletters from Outlook and archive them."""
    settings = get_settings()

    if not settings.is_configured:
        rprint("[red]Error:[/red] Azure AD not configured. Run: [cyan]newsletter-archiver config setup[/cyan]")
        raise typer.Exit(1)

    settings.ensure_dirs()
    db = DatabaseManager()
    client = GraphClient()

    # Authenticate
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
    ) as progress:
        progress.add_task("Authenticating with Microsoft Graph...", total=None)
        try:
            client.authenticate()
        except AuthError as e:
            rprint(f"[red]Authentication failed:[/red] {e}")
            raise typer.Exit(1)

    rprint(f"[green]✓[/green] Authenticated")
    rprint(f"Fetching emails from the last [bold]{days_back}[/bold] days...")
    if sender:
        rprint(f"Filtering by sender: [bold]{sender}[/bold]")

    # Fetch emails
    try:
        messages = client.fetch_emails(
            days_back=days_back,
            sender_filter=sender,
        )
    except FetchError as e:
        rprint(f"[red]Fetch failed:[/red] {e}")
        raise typer.Exit(1)

    if not messages:
        rprint("[yellow]No emails found for the given criteria.[/yellow]")
        raise typer.Exit(0)

    rprint(f"Found [bold]{len(messages)}[/bold] emails. Processing...")

    # Process each email
    saved = 0
    skipped = 0
    not_newsletter = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
    ) as progress:
        task = progress.add_task("Processing emails...", total=len(messages))

        for message in messages:
            parsed = parse_message(message)

            # Skip if not a newsletter (unless --all)
            if not all_mail and not parsed.is_newsletter:
                not_newsletter += 1
                progress.advance(task)
                continue

            # Skip if already archived
            if db.newsletter_exists(parsed.message_id):
                skipped += 1
                progress.advance(task)
                continue

            # Convert content
            markdown_body = html_to_markdown(parsed.html_body)
            markdown_doc = build_markdown_document(
                subject=parsed.subject,
                sender_name=parsed.sender_name,
                sender_email=parsed.sender_email,
                received_date=parsed.received_date.isoformat(),
                markdown_body=markdown_body,
            )

            word_count = calculate_word_count(markdown_body)
            reading_time = calculate_reading_time(word_count)

            # Save files
            base_path = get_archive_path(
                sender_name=parsed.sender_name,
                sender_email=parsed.sender_email,
                received_date=parsed.received_date,
                subject=parsed.subject,
            )
            md_path, html_path = save_newsletter_files(
                base_path=base_path,
                markdown_content=markdown_doc,
                html_content=parsed.html_body,
            )

            # Save to database
            db.save_newsletter(
                message_id=parsed.message_id,
                subject=parsed.subject,
                sender_email=parsed.sender_email,
                sender_name=parsed.sender_name,
                received_date=parsed.received_date,
                markdown_path=str(md_path),
                html_path=str(html_path),
                word_count=word_count,
                reading_time_minutes=reading_time,
            )

            # Track sender
            db.upsert_sender(
                email=parsed.sender_email,
                name=parsed.sender_name,
            )

            saved += 1
            progress.advance(task)

    # Summary
    rprint()
    rprint(f"[green]✓[/green] Done!")
    rprint(f"  Saved: [bold green]{saved}[/bold green] newsletters")
    if skipped:
        rprint(f"  Skipped (already archived): [yellow]{skipped}[/yellow]")
    if not_newsletter:
        rprint(f"  Skipped (not newsletters): [dim]{not_newsletter}[/dim]")
    rprint(f"  Total archived: [bold]{db.get_newsletter_count()}[/bold]")
