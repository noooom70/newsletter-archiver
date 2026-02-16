"""Archive file organization and management."""

import re
import unicodedata
from datetime import datetime
from pathlib import Path

from newsletter_archiver.core.config import get_settings


def slugify(text: str, max_length: int = 80) -> str:
    """Convert text to a filesystem-safe slug."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text).strip("-")
    return text[:max_length]


def get_sender_dirname(sender_name: str, sender_email: str) -> str:
    """Create a directory name from sender info.

    Checks publications mapping first; falls back to slugified sender name.
    """
    publications = get_settings().load_publications()
    if sender_email in publications:
        return slugify(publications[sender_email])
    name = sender_name or sender_email.split("@")[0]
    return slugify(name)


def get_archive_path(
    sender_name: str,
    sender_email: str,
    received_date: datetime,
    subject: str,
) -> Path:
    """Build the archive path for a newsletter.

    Layout: archives/YYYY/MM/sender_name/YYYY-MM-DD_subject-slug.md
    """
    settings = get_settings()
    sender_dir = get_sender_dirname(sender_name, sender_email)
    date_prefix = received_date.strftime("%Y-%m-%d")
    subject_slug = slugify(subject)
    filename = f"{date_prefix}_{subject_slug}"

    return (
        settings.archives_dir
        / received_date.strftime("%Y")
        / received_date.strftime("%m")
        / sender_dir
        / filename
    )


def save_newsletter_files(
    base_path: Path, markdown_content: str, html_content: str
) -> tuple[Path, Path]:
    """Save markdown and HTML files for a newsletter.

    Returns (markdown_path, html_path).
    """
    base_path.parent.mkdir(parents=True, exist_ok=True)

    md_path = base_path.with_suffix(".md")
    html_path = base_path.with_suffix(".html")

    md_path.write_text(markdown_content, encoding="utf-8")
    html_path.write_text(html_content, encoding="utf-8")

    return md_path, html_path
