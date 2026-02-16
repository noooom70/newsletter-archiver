"""Archive command - manage archive directory structure."""

import os
import shutil
from pathlib import Path

import typer
from rich import print as rprint

from newsletter_archiver.core.config import get_settings
from newsletter_archiver.core.database import Newsletter, get_session
from newsletter_archiver.fetcher.content_extractor import strip_invisible_chars
from newsletter_archiver.storage.file_manager import slugify

app = typer.Typer(no_args_is_help=True)


@app.command()
def migrate(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without moving files"),
):
    """Migrate archive directories to publication-based naming.

    Uses the publications.yaml mapping to rename sender directories
    from sender-name to publication-name. Updates DB paths to match.
    """
    settings = get_settings()
    publications = settings.load_publications()

    if not publications:
        rprint("[yellow]No publications.yaml found or file is empty.[/yellow]")
        rprint(f"  Expected at: {settings.publications_path}")
        raise typer.Exit(1)

    session = get_session(settings.db_url)
    archives_dir = settings.archives_dir

    try:
        newsletters = session.query(Newsletter).all()
        moved = 0
        skipped = 0
        errors = 0

        for nl in newsletters:
            pub_name = publications.get(nl.sender_email)
            if not pub_name:
                skipped += 1
                continue

            new_dirname = slugify(pub_name)
            old_dirname = slugify(nl.sender_name) if nl.sender_name else slugify(nl.sender_email.split("@")[0])

            if new_dirname == old_dirname:
                skipped += 1
                continue

            # Determine year/month path components from received_date
            year = nl.received_date.strftime("%Y")
            month = nl.received_date.strftime("%m")

            old_sender_dir = archives_dir / year / month / old_dirname
            new_sender_dir = archives_dir / year / month / new_dirname

            # Move individual files (md + html)
            files_moved = False
            for path_attr in ("markdown_path", "html_path"):
                old_path_str = getattr(nl, path_attr)
                if not old_path_str:
                    continue

                old_path = Path(old_path_str)
                if not old_path.exists():
                    continue

                # Compute new path: replace old dirname with new dirname
                new_path = new_sender_dir / old_path.name

                if dry_run:
                    rprint(f"  [dim]{old_path}[/dim]")
                    rprint(f"  [green]→ {new_path}[/green]")
                    rprint()
                    files_moved = True
                else:
                    new_path.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        shutil.move(str(old_path), str(new_path))
                        setattr(nl, path_attr, str(new_path))
                        files_moved = True
                    except OSError as e:
                        rprint(f"  [red]Error moving {old_path}: {e}[/red]")
                        errors += 1

            if files_moved:
                moved += 1

        if not dry_run:
            session.commit()

            # Remove empty directories
            empties_removed = _remove_empty_dirs(archives_dir)
            if empties_removed:
                rprint(f"  Removed {empties_removed} empty directories")

        # Summary
        rprint()
        label = "Would move" if dry_run else "Moved"
        rprint(f"[bold]{label}: {moved}[/bold] newsletters, skipped: {skipped}, errors: {errors}")
        if dry_run and moved:
            rprint("\n[dim]Run without --dry-run to execute.[/dim]")

    finally:
        session.close()


@app.command()
def clean(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without modifying files"),
):
    """Strip invisible Unicode padding from existing markdown files.

    Rewrites .md files in-place to remove zero-width spaces, soft hyphens,
    and other invisible characters left over from email preheader padding.
    """
    settings = get_settings()
    session = get_session(settings.db_url)

    try:
        newsletters = session.query(Newsletter).all()
        cleaned = 0
        skipped = 0

        for nl in newsletters:
            if not nl.markdown_path:
                continue

            path = Path(nl.markdown_path)
            if not path.exists():
                continue

            original = path.read_text(encoding="utf-8")
            result = strip_invisible_chars(original)

            if result == original:
                skipped += 1
                continue

            if dry_run:
                saved = len(original) - len(result)
                rprint(f"  [green]{path.name}[/green] — {saved} chars removed")
            else:
                path.write_text(result, encoding="utf-8")

            cleaned += 1

        label = "Would clean" if dry_run else "Cleaned"
        rprint(f"\n[bold]{label}: {cleaned}[/bold] files, skipped: {skipped} (already clean)")
        if dry_run and cleaned:
            rprint("[dim]Run without --dry-run to execute.[/dim]")

    finally:
        session.close()


def _remove_empty_dirs(root: Path) -> int:
    """Walk bottom-up and remove empty directories. Returns count removed."""
    count = 0
    for dirpath, dirnames, filenames in os.walk(str(root), topdown=False):
        p = Path(dirpath)
        if p == root:
            continue
        try:
            if not any(p.iterdir()):
                p.rmdir()
                count += 1
        except OSError:
            pass
    return count
