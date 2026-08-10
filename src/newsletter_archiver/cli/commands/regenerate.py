"""Regenerate command - rebuild markdown retrieval copies from stored HTML."""

from typing import Optional

import typer
from rich import print as rprint

from newsletter_archiver.core.config import get_settings
from newsletter_archiver.storage.regenerator import regenerate_archive


def app(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Report what would change without writing anything"
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit", help="Process only the first N files (sorted order)"
    ),
):
    """Rebuild every .md retrieval copy from its stored .html (never refetches)."""
    settings = get_settings()

    db = None
    if not dry_run:
        from newsletter_archiver.storage.db_manager import DatabaseManager

        db = DatabaseManager()

    mode = "Dry run" if dry_run else "Regenerating"
    rprint(f"[bold]{mode}: scanning {settings.archives_dir}...[/bold]")

    report = regenerate_archive(
        settings.archives_dir, db=db, dry_run=dry_run, limit=limit
    )

    changed = report.count("regenerated")
    rprint(
        f"\n[bold]Results:[/bold] {changed} changed, "
        f"{report.count('unchanged')} unchanged, "
        f"{report.count('skipped_no_md')} without .md, "
        f"{report.count('skipped_bad_frontmatter')} bad frontmatter, "
        f"{report.count('failed')} failed"
    )
    if report.total_before:
        pct = 100 * (report.total_before - report.total_after) / report.total_before
        rprint(
            f"Size: {report.total_before:,} -> {report.total_after:,} chars "
            f"({pct:.1f}% smaller)"
        )
    if report.total_unwrap_failures:
        rprint(f"[yellow]SafeLink unwrap failures: {report.total_unwrap_failures}[/yellow]")

    top = sorted(
        (o for o in report.outcomes if o.status == "regenerated"),
        key=lambda o: o.after_chars - o.before_chars,
    )[:10]
    if top and dry_run:
        rprint("\n[bold]Top reductions:[/bold]")
        for o in top:
            rprint(f"  {o.before_chars:>9,} -> {o.after_chars:>9,}  {o.html_path.name}")

    for o in report.outcomes:
        if o.status == "failed":
            rprint(f"[red]FAILED[/red] {o.html_path}: {o.error}")

    if dry_run:
        rprint("\n[yellow]Dry run: no files written.[/yellow]")
    else:
        if report.missing_db_rows:
            rprint(
                f"[yellow]{report.missing_db_rows} regenerated file(s) had no "
                f"database row (metrics not refreshed).[/yellow]"
            )
        if changed:
            rprint(
                "\n[yellow]Search indexes are now stale. Run "
                "'newsletter-archiver index build --reindex' to refresh "
                "search indexes.[/yellow]"
            )
    if report.count("failed"):
        raise typer.Exit(1)
