"""Configuration management commands."""

from pathlib import Path

import typer
from rich import print as rprint
from rich.panel import Panel
from rich.table import Table

from newsletter_archiver.core.config import get_settings
from newsletter_archiver.storage.db_manager import DatabaseManager

app = typer.Typer()


@app.command()
def setup():
    """Initialize archive directories and database."""
    rprint(Panel.fit(
        "[bold blue]Newsletter Archiver - Setup[/bold blue]\n\n"
        "This will initialize your archive and prepare for first login.\n"
        "No Azure portal registration needed!",
        border_style="blue",
    ))

    settings = get_settings()
    settings.ensure_dirs()
    rprint(f"[green]✓[/green] Archive directory created at [bold]{settings.archive_dir}[/bold]")

    DatabaseManager()
    rprint(f"[green]✓[/green] Database initialized at [bold]{settings.db_path}[/bold]")

    rprint("\n[bold]Next step:[/bold] Run [cyan]newsletter-archiver fetch --days-back 1[/cyan]")
    rprint("  You'll be given a code to enter at [cyan]https://microsoft.com/devicelogin[/cyan]")
    rprint("  Sign in with your Microsoft account and approve access.")
    rprint("  After that, fetching works automatically with no prompts.")

    rprint(Panel.fit(
        "[bold green]Setup complete![/bold green]\n"
        "Run [cyan]newsletter-archiver fetch[/cyan] to start archiving.",
        border_style="green",
    ))


@app.command()
def show():
    """Show current configuration."""
    settings = get_settings()

    table = Table(title="Newsletter Archiver Configuration")
    table.add_column("Setting", style="bold")
    table.add_column("Value")

    table.add_row("Client ID", settings.azure_client_id[:8] + "...")
    table.add_row("Outlook Email", settings.outlook_email)
    table.add_row("Archive Dir", str(settings.archive_dir))
    table.add_row("Database", str(settings.db_path))
    table.add_row("Token Cache", "[green]exists[/green]" if settings.token_path.exists() else "[yellow]not yet authenticated[/yellow]")

    try:
        db = DatabaseManager()
        table.add_row("Newsletters Archived", str(db.get_newsletter_count()))
        table.add_row("Known Senders", str(db.get_sender_count()))
    except Exception:
        pass

    rprint(table)


