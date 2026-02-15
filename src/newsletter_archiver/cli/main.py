"""Main Typer application and command registration."""

import typer

from newsletter_archiver.cli.commands.config import app as config_app
from newsletter_archiver.cli.commands.fetch import app as fetch_app
from newsletter_archiver.cli.commands.review import app as review_app
from newsletter_archiver.cli.commands.senders import app as senders_app

app = typer.Typer(
    name="newsletter-archiver",
    help="Archive and search email newsletters from Outlook.",
    no_args_is_help=True,
)

app.add_typer(config_app, name="config", help="Manage configuration.")
app.add_typer(senders_app, name="senders", help="Manage newsletter senders (approve, deny, list).")
app.command(name="fetch")(fetch_app)
app.command(name="review")(review_app)


if __name__ == "__main__":
    app()
