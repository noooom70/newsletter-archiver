"""Review command - approve or deny individual queued emails."""

import typer
from rich import print as rprint
from rich.prompt import Prompt

from newsletter_archiver.core.config import get_settings
from newsletter_archiver.fetcher.content_extractor import (
    build_markdown_document,
    calculate_reading_time,
    calculate_word_count,
    html_to_markdown,
)
from newsletter_archiver.storage.db_manager import DatabaseManager
from newsletter_archiver.storage.file_manager import (
    get_archive_path,
    save_newsletter_files,
)


def app():
    """Review and approve/deny individual queued emails.

    Emails from review-mode senders are queued during fetch.
    Use this command to approve or deny each email individually.
    """
    settings = get_settings()
    settings.ensure_dirs()
    db = DatabaseManager()

    pending = db.get_pending_emails()

    if not pending:
        rprint("[green]No emails pending review.[/green]")
        return

    rprint(f"\n[bold]{len(pending)} email(s) pending review:[/bold]\n")

    approved = 0
    denied = 0

    for i, email in enumerate(pending, 1):
        rprint(
            f"[bold]({i}/{len(pending)})[/bold] "
            f"{email.sender_name or email.sender_email} [dim]<{email.sender_email}>[/dim]"
        )
        rprint(f"  Subject: [italic]{email.subject}[/italic]")
        rprint(f"  Date: {email.received_date:%Y-%m-%d %H:%M}")

        choice = Prompt.ask(
            "  Action: \\[a]pprove, \\[d]eny, \\[s]kip, \\[q]uit",
            choices=["a", "d", "s", "q"],
            default="s",
        )

        if choice == "a":
            # Archive the email
            markdown_body = html_to_markdown(email.html_body)
            markdown_doc = build_markdown_document(
                subject=email.subject,
                sender_name=email.sender_name,
                sender_email=email.sender_email,
                received_date=email.received_date.isoformat(),
                markdown_body=markdown_body,
            )

            word_count = calculate_word_count(markdown_body)
            reading_time = calculate_reading_time(word_count)

            base_path = get_archive_path(
                sender_name=email.sender_name,
                sender_email=email.sender_email,
                received_date=email.received_date,
                subject=email.subject,
            )
            md_path, html_path = save_newsletter_files(
                base_path=base_path,
                markdown_content=markdown_doc,
                html_content=email.html_body,
            )

            db.save_newsletter(
                message_id=email.message_id,
                subject=email.subject,
                sender_email=email.sender_email,
                sender_name=email.sender_name,
                received_date=email.received_date,
                markdown_path=str(md_path),
                html_path=str(html_path),
                word_count=word_count,
                reading_time_minutes=reading_time,
            )

            db.delete_pending_email(email.id)
            approved += 1
            rprint(f"  [green]Archived[/green]")
        elif choice == "d":
            db.delete_pending_email(email.id)
            denied += 1
            rprint(f"  [red]Denied[/red]")
        elif choice == "s":
            rprint(f"  [dim]Skipped[/dim]")
        elif choice == "q":
            rprint("[dim]Review stopped.[/dim]")
            break
        rprint()

    # Summary
    remaining = len(db.get_pending_emails())
    rprint(f"Approved: [green]{approved}[/green], Denied: [red]{denied}[/red]", end="")
    if remaining:
        rprint(f", Remaining: [yellow]{remaining}[/yellow]")
    else:
        rprint()
