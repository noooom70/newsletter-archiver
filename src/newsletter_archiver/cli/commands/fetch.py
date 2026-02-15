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
from newsletter_archiver.fetcher.email_parser import _is_transactional_subject, parse_message
from newsletter_archiver.fetcher.graph_client import GraphClient
from newsletter_archiver.storage.db_manager import DatabaseManager
from newsletter_archiver.storage.file_manager import (
    get_archive_path,
    save_newsletter_files,
)


def app(
    days_back: int = typer.Option(7, "--days-back", "-d", help="Number of days back to fetch"),
    sender: Optional[str] = typer.Option(None, "--sender", "-s", help="Filter by sender email or domain"),
    scan: bool = typer.Option(False, "--scan", help="Scan for new newsletter senders without archiving"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be filtered out without archiving or queuing"),
):
    """Fetch newsletters from Outlook and archive them.

    By default, only archives emails from approved senders.
    Use --scan to discover new newsletter senders for review.
    Use --dry-run to audit the newsletter detection filter.
    """
    settings = get_settings()

    if not settings.is_configured:
        rprint("[red]Error:[/red] Not configured. Run: [cyan]newsletter-archiver config setup[/cyan]")
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

    approved_senders = db.get_approved_sender_emails()

    if dry_run:
        _dry_run(messages, approved_senders)
    elif scan:
        _scan_for_senders(messages, db, approved_senders)
    else:
        _archive_approved(messages, db, approved_senders)


def _dry_run(messages: list, approved_senders: set[str]):
    """Show how the transactional subject filter would classify each email from approved senders."""
    accepted = []
    filtered = []

    for message in messages:
        parsed = parse_message(message)
        if parsed.sender_email not in approved_senders:
            continue
        if _is_transactional_subject(parsed.subject):
            filtered.append(parsed)
        else:
            accepted.append(parsed)

    if filtered:
        rprint(f"\n[red bold]Filtered out ({len(filtered)}):[/red bold]")
        for p in filtered:
            rprint(f"  [red]✗[/red] {p.sender_email}: {p.subject}")
    else:
        rprint(f"\n[green]No emails filtered out.[/green]")

    if accepted:
        rprint(f"\n[green bold]Would archive/queue ({len(accepted)}):[/green bold]")
        for p in accepted:
            rprint(f"  [green]✓[/green] {p.sender_email}: {p.subject}")

    rprint(f"\nTotal from approved senders: {len(accepted) + len(filtered)} "
           f"(accepted: {len(accepted)}, filtered: {len(filtered)})")


def _scan_for_senders(messages: list, db: DatabaseManager, approved_senders: set[str]):
    """Scan emails for newsletter senders and add as pending for review."""
    new_senders = 0
    known = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
    ) as progress:
        task = progress.add_task("Scanning for newsletters...", total=len(messages))

        for message in messages:
            parsed = parse_message(message)

            if not parsed.is_newsletter:
                progress.advance(task)
                continue

            existing = db.get_sender(parsed.sender_email)
            if existing:
                known += 1
            else:
                db.upsert_sender(
                    email=parsed.sender_email,
                    name=parsed.sender_name,
                    status="pending",
                    sample_subject=parsed.subject,
                )
                new_senders += 1

            progress.advance(task)

    rprint()
    rprint(f"[green]✓[/green] Scan complete!")
    if new_senders:
        rprint(f"  New senders found: [bold yellow]{new_senders}[/bold yellow]")
        rprint(f"  Run [cyan]newsletter-archiver senders review[/cyan] to approve or deny them.")
    else:
        rprint(f"  No new newsletter senders found.")
    if known:
        rprint(f"  Already known: {known}")


def _archive_approved(messages: list, db: DatabaseManager, approved_senders: set[str]):
    """Archive emails from approved senders only.

    Auto-mode senders are archived immediately.
    Review-mode senders have emails queued in pending_emails for individual approval.
    """
    if not approved_senders:
        rprint("[yellow]No approved senders yet.[/yellow]")
        rprint("Run [cyan]newsletter-archiver fetch --scan[/cyan] to discover newsletter senders,")
        rprint("then [cyan]newsletter-archiver senders review[/cyan] to approve them.")
        raise typer.Exit(0)

    # Build a set of auto-mode sender emails for fast lookup
    auto_senders = {s.email for s in db.get_senders_by_mode("auto")}

    saved = 0
    queued = 0
    skipped = 0
    not_approved = 0
    new_pending = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
    ) as progress:
        task = progress.add_task("Archiving newsletters...", total=len(messages))

        for message in messages:
            parsed = parse_message(message)

            # Only process from approved senders
            if parsed.sender_email not in approved_senders:
                # If it looks like a newsletter from an unknown sender, add as pending
                if parsed.is_newsletter and not db.get_sender(parsed.sender_email):
                    db.upsert_sender(
                        email=parsed.sender_email,
                        name=parsed.sender_name,
                        status="pending",
                        sample_subject=parsed.subject,
                    )
                    new_pending += 1
                not_approved += 1
                progress.advance(task)
                continue

            # For approved senders, only skip obvious transactional emails.
            # The user already vouched for this sender — don't require
            # positive newsletter signals on every email.
            if _is_transactional_subject(parsed.subject):
                skipped += 1
                progress.advance(task)
                continue

            # Skip if already archived or already queued
            if db.newsletter_exists(parsed.message_id):
                skipped += 1
                progress.advance(task)
                continue
            if db.pending_email_exists(parsed.message_id):
                skipped += 1
                progress.advance(task)
                continue

            # Route based on sender mode
            if parsed.sender_email in auto_senders:
                # Auto mode: archive immediately
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
                saved += 1
            else:
                # Review mode: queue for individual approval
                db.save_pending_email(
                    message_id=parsed.message_id,
                    subject=parsed.subject,
                    sender_email=parsed.sender_email,
                    sender_name=parsed.sender_name,
                    received_date=parsed.received_date,
                    html_body=parsed.html_body,
                )
                queued += 1

            progress.advance(task)

    # Summary
    rprint()
    rprint(f"[green]✓[/green] Done!")
    if saved:
        rprint(f"  Archived: [bold green]{saved}[/bold green] newsletters")
    if queued:
        rprint(f"  Queued for review: [bold yellow]{queued}[/bold yellow]")
        rprint(f"  Run [cyan]newsletter-archiver review[/cyan] to approve or deny them.")
    if skipped:
        rprint(f"  Already archived/queued: [dim]{skipped}[/dim]")
    if not_approved:
        rprint(f"  Skipped (not approved): [dim]{not_approved}[/dim]")
    if new_pending:
        rprint(f"  New senders discovered: [yellow]{new_pending}[/yellow]")
        rprint(f"  Run [cyan]newsletter-archiver senders review[/cyan] to approve them.")
    rprint(f"  Total archived: [bold]{db.get_newsletter_count()}[/bold]")
