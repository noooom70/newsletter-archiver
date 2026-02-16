"""Main Typer application and command registration."""

import typer

from newsletter_archiver.cli.commands.archive import app as archive_app
from newsletter_archiver.cli.commands.config import app as config_app
from newsletter_archiver.cli.commands.fetch import app as fetch_app
from newsletter_archiver.cli.commands.index import app as index_app
from newsletter_archiver.cli.commands.review import app as review_app
from newsletter_archiver.cli.commands.search import app as search_app
from newsletter_archiver.cli.commands.senders import app as senders_app

app = typer.Typer(
    name="newsletter-archiver",
    help="Archive and search email newsletters from Outlook.",
    no_args_is_help=True,
)

app.add_typer(archive_app, name="archive", help="Manage archive directory structure.")
app.add_typer(config_app, name="config", help="Manage configuration.")
app.add_typer(senders_app, name="senders", help="Manage newsletter senders (approve, deny, list).")
app.add_typer(index_app, name="index", help="Build and manage search indexes.")
app.add_typer(search_app, name="search", help="Search archived newsletters.")
app.command(name="fetch")(fetch_app)
app.command(name="review")(review_app)


if __name__ == "__main__":
    app()
