"""Configuration management commands."""

from pathlib import Path

import typer
from rich import print as rprint
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from newsletter_archiver.core.config import get_settings
from newsletter_archiver.storage.db_manager import DatabaseManager

app = typer.Typer()


@app.command()
def setup():
    """Guided Azure AD app registration and configuration."""
    rprint(Panel.fit(
        "[bold blue]Newsletter Archiver - Azure AD Setup[/bold blue]\n\n"
        "This will walk you through registering an Azure AD app\n"
        "to access your Outlook emails via Microsoft Graph API.",
        border_style="blue",
    ))

    rprint("\n[bold]Step 1: Register an Azure AD Application[/bold]")
    rprint("  1. Go to [link=https://portal.azure.com]https://portal.azure.com[/link]")
    rprint("  2. Search for [bold]App registrations[/bold] and click it")
    rprint("  3. Click [bold]+ New registration[/bold]")
    rprint("  4. Name: [cyan]Newsletter Archiver[/cyan]")
    rprint("  5. Supported account types: [cyan]Personal Microsoft accounts only[/cyan]")
    rprint("  6. Redirect URI: Select [cyan]Web[/cyan] → enter [cyan]http://localhost[/cyan]")
    rprint("  7. Click [bold]Register[/bold]")
    rprint()

    client_id = Prompt.ask("[bold]Enter your Application (client) ID[/bold]")

    rprint("\n[bold]Step 2: Create a Client Secret[/bold]")
    rprint("  1. In your app page, go to [bold]Certificates & secrets[/bold]")
    rprint("  2. Click [bold]+ New client secret[/bold]")
    rprint("  3. Description: [cyan]newsletter-archiver[/cyan], Expiry: [cyan]24 months[/cyan]")
    rprint("  4. Click [bold]Add[/bold] and copy the [bold]Value[/bold] (not the Secret ID)")
    rprint()

    client_secret = Prompt.ask("[bold]Enter your Client Secret value[/bold]")

    rprint("\n[bold]Step 3: Add API Permissions[/bold]")
    rprint("  1. Go to [bold]API permissions[/bold]")
    rprint("  2. Click [bold]+ Add a permission[/bold]")
    rprint("  3. Select [bold]Microsoft Graph[/bold] → [bold]Delegated permissions[/bold]")
    rprint("  4. Search and add: [cyan]Mail.Read[/cyan] and [cyan]Mail.ReadBasic[/cyan]")
    rprint("  5. Click [bold]Add permissions[/bold]")
    rprint()

    # Write .env file
    env_path = Path(".env")
    env_content = (
        f"AZURE_CLIENT_ID={client_id}\n"
        f"AZURE_CLIENT_SECRET={client_secret}\n"
    )
    env_path.write_text(env_content)
    rprint(f"[green]✓[/green] Credentials saved to [bold]{env_path.absolute()}[/bold]")

    # Ensure directories exist
    settings = get_settings()
    settings.ensure_dirs()
    rprint(f"[green]✓[/green] Archive directory created at [bold]{settings.archive_dir}[/bold]")

    # Initialize database
    DatabaseManager()
    rprint(f"[green]✓[/green] Database initialized at [bold]{settings.db_path}[/bold]")

    rprint("\n[bold]Step 4: First-time Authentication[/bold]")
    rprint("  Run: [cyan]newsletter-archiver fetch --days-back 1[/cyan]")
    rprint("  This will open a browser window for you to log in to your Microsoft account.")
    rprint("  After login, your token will be cached locally.")

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

    table.add_row("Azure Client ID", settings.azure_client_id[:8] + "..." if settings.azure_client_id else "[red]Not set[/red]")
    table.add_row("Client Secret", "****" if settings.azure_client_secret else "[red]Not set[/red]")
    table.add_row("Outlook Email", settings.outlook_email)
    table.add_row("Archive Dir", str(settings.archive_dir))
    table.add_row("Database", str(settings.db_path))
    table.add_row("Configured", "[green]Yes[/green]" if settings.is_configured else "[red]No[/red]")

    if settings.is_configured:
        try:
            db = DatabaseManager()
            table.add_row("Newsletters Archived", str(db.get_newsletter_count()))
            table.add_row("Known Senders", str(db.get_sender_count()))
        except Exception:
            pass

    rprint(table)


@app.command("add-sender")
def add_sender(
    email: str = typer.Argument(help="Sender email address to add to allowlist"),
    name: str = typer.Option("", help="Display name for the sender"),
):
    """Add a sender to the newsletter allowlist."""
    settings = get_settings()
    settings.ensure_dirs()

    db = DatabaseManager()
    sender = db.upsert_sender(email=email, name=name)
    rprint(f"[green]✓[/green] Added sender: [bold]{sender.email}[/bold] ({sender.name or 'no name'})")
