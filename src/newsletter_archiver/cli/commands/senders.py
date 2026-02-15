"""Sender management commands - review, list, add, remove."""

from typing import Optional

import typer
from rich import print as rprint
from rich.prompt import Prompt
from rich.table import Table

from newsletter_archiver.core.config import get_settings
from newsletter_archiver.storage.db_manager import DatabaseManager

app = typer.Typer()


@app.command()
def review():
    """Interactively review pending newsletter senders (approve/deny)."""
    settings = get_settings()
    settings.ensure_dirs()
    db = DatabaseManager()

    pending = db.get_senders_by_status("pending")

    if not pending:
        rprint("[green]No pending senders to review.[/green]")
        rprint("Run [cyan]newsletter-archiver fetch --scan[/cyan] to discover new senders.")
        return

    rprint(f"\n[bold]{len(pending)} pending sender(s) to review:[/bold]\n")

    for i, sender in enumerate(pending, 1):
        rprint(f"[bold]({i}/{len(pending)})[/bold] {sender.name or '(no name)'} [dim]<{sender.email}>[/dim]")
        if sender.sample_subject:
            rprint(f"  Example: [italic]{sender.sample_subject}[/italic]")

        choice = Prompt.ask(
            "  Action",
            choices=["a", "d", "s", "q"],
            default="s",
        )

        if choice == "a":
            db.set_sender_status(sender.email, "approved")
            rprint(f"  [green]Approved[/green]")
        elif choice == "d":
            db.set_sender_status(sender.email, "denied")
            rprint(f"  [red]Denied[/red]")
        elif choice == "s":
            rprint(f"  [dim]Skipped (still pending)[/dim]")
        elif choice == "q":
            rprint("[dim]Review stopped.[/dim]")
            break
        rprint()

    # Summary
    approved = len(db.get_senders_by_status("approved"))
    pending_left = len(db.get_senders_by_status("pending"))
    denied = len(db.get_senders_by_status("denied"))
    rprint(f"Senders: [green]{approved} approved[/green], [yellow]{pending_left} pending[/yellow], [red]{denied} denied[/red]")

    if approved:
        rprint(f"\nRun [cyan]newsletter-archiver fetch[/cyan] to archive from approved senders.")


@app.command("list")
def list_senders(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status: approved, pending, denied"),
):
    """Show all known senders and their status."""
    settings = get_settings()
    settings.ensure_dirs()
    db = DatabaseManager()

    if status:
        if status not in ("approved", "pending", "denied"):
            rprint(f"[red]Invalid status:[/red] {status}. Use: approved, pending, denied")
            raise typer.Exit(1)
        senders = db.get_senders_by_status(status)
    else:
        senders = db.get_all_senders()

    if not senders:
        rprint("[yellow]No senders found.[/yellow]")
        rprint("Run [cyan]newsletter-archiver fetch --scan[/cyan] to discover newsletter senders.")
        return

    table = Table(title="Newsletter Senders")
    table.add_column("Status", style="bold")
    table.add_column("Name")
    table.add_column("Email")
    table.add_column("Example Subject")

    status_styles = {
        "approved": "[green]approved[/green]",
        "pending": "[yellow]pending[/yellow]",
        "denied": "[red]denied[/red]",
    }

    for s in senders:
        table.add_row(
            status_styles.get(s.status, s.status),
            s.name or "-",
            s.email,
            (s.sample_subject[:50] + "...") if len(s.sample_subject or "") > 50 else (s.sample_subject or "-"),
        )

    rprint(table)


@app.command()
def add(
    email: str = typer.Argument(help="Sender email address"),
    name: str = typer.Option("", "--name", "-n", help="Display name for the sender"),
):
    """Manually add a sender as approved."""
    settings = get_settings()
    settings.ensure_dirs()
    db = DatabaseManager()

    existing = db.get_sender(email)
    if existing:
        db.set_sender_status(email, "approved")
        rprint(f"[green]Approved[/green] existing sender: [bold]{email}[/bold]")
    else:
        db.upsert_sender(email=email, name=name, status="approved")
        rprint(f"[green]Added and approved[/green]: [bold]{email}[/bold]")


@app.command()
def remove(
    email: str = typer.Argument(help="Sender email address to deny"),
):
    """Deny a sender (stop archiving their emails)."""
    settings = get_settings()
    settings.ensure_dirs()
    db = DatabaseManager()

    sender = db.set_sender_status(email, "denied")
    if sender:
        rprint(f"[red]Denied[/red]: [bold]{email}[/bold]")
    else:
        rprint(f"[yellow]Sender not found:[/yellow] {email}")
