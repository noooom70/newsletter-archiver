"""Main Typer application and command registration."""

import typer

from newsletter_archiver.cli.commands.config import app as config_app
from newsletter_archiver.cli.commands.fetch import app as fetch_app

app = typer.Typer(
    name="newsletter-archiver",
    help="Archive and search email newsletters from Outlook.",
    no_args_is_help=True,
)

app.add_typer(config_app, name="config", help="Manage configuration and Azure AD setup.")
app.command(name="fetch")(fetch_app)


if __name__ == "__main__":
    app()
