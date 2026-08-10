"""Regenerate markdown retrieval copies from stored HTML.

The .html files are the reading archive and are only ever read. Each .md
keeps its frontmatter verbatim; only the body is re-extracted.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from newsletter_archiver.fetcher.content_extractor import (
    calculate_reading_time,
    calculate_word_count,
    extract_markdown,
)
from newsletter_archiver.storage.db_manager import DatabaseManager

_FM_DELIM = "\n---\n"


@dataclass
class FileOutcome:
    html_path: Path
    status: str
    before_chars: int = 0
    after_chars: int = 0
    unwrap_failures: int = 0
    db_row_updated: bool = False
    error: str = ""


@dataclass
class RegenReport:
    outcomes: list[FileOutcome] = field(default_factory=list)
    dry_run: bool = False

    def count(self, status: str) -> int:
        return sum(1 for o in self.outcomes if o.status == status)

    @property
    def total_before(self) -> int:
        return sum(o.before_chars for o in self.outcomes)

    @property
    def total_after(self) -> int:
        return sum(o.after_chars for o in self.outcomes)

    @property
    def total_unwrap_failures(self) -> int:
        return sum(o.unwrap_failures for o in self.outcomes)

    @property
    def missing_db_rows(self) -> int:
        """Regenerated files whose markdown_path matched no DB row.

        Only meaningful on a non-dry run: a dry run never touches the DB, so
        every outcome reports db_row_updated=False.
        """
        return sum(
            1
            for o in self.outcomes
            if o.status == "regenerated" and not o.db_row_updated
        )


def split_frontmatter(md_text: str) -> Optional[tuple[str, str]]:
    """Split '---\\n...\\n---\\n' frontmatter from body.

    Returns (frontmatter_block_including_delimiters, body) or None when the
    document does not start with a well-formed frontmatter block.
    """
    if not md_text.startswith("---\n"):
        return None
    end = md_text.find(_FM_DELIM, 4)
    if end == -1:
        return None
    fm = md_text[: end + len(_FM_DELIM)]
    body = md_text[end + len(_FM_DELIM):].lstrip("\n")
    return fm, body


def regenerate_file(
    html_path: Path, db: Optional[DatabaseManager], dry_run: bool
) -> FileOutcome:
    md_path = html_path.with_suffix(".md")
    if not md_path.exists():
        return FileOutcome(html_path, "skipped_no_md")
    try:
        old_doc = md_path.read_text(encoding="utf-8")
        parts = split_frontmatter(old_doc)
        if parts is None:
            return FileOutcome(html_path, "skipped_bad_frontmatter")
        frontmatter, _ = parts

        result = extract_markdown(html_path.read_text(encoding="utf-8"))
        new_doc = frontmatter + "\n" + result.markdown + "\n"

        outcome = FileOutcome(
            html_path,
            "unchanged",
            before_chars=len(old_doc),
            after_chars=len(new_doc),
            unwrap_failures=result.unwrap_failures,
        )
        if new_doc == old_doc:
            return outcome

        outcome.status = "regenerated"
        if not dry_run:
            md_path.write_text(new_doc, encoding="utf-8")
            if db is not None:
                wc = calculate_word_count(result.markdown)
                outcome.db_row_updated = db.update_newsletter_metrics(
                    str(md_path), wc, calculate_reading_time(wc)
                )
        return outcome
    except Exception as exc:  # noqa: BLE001 - per-file isolation is the contract
        return FileOutcome(html_path, "failed", error=str(exc))


def regenerate_archive(
    archives_dir: Path,
    db: Optional[DatabaseManager] = None,
    dry_run: bool = False,
    limit: Optional[int] = None,
) -> RegenReport:
    """Regenerate every paired .md under archives_dir from its .html."""
    html_files = sorted(archives_dir.rglob("*.html"))
    if limit is not None:
        html_files = html_files[:limit]
    report = RegenReport(dry_run=dry_run)
    for html_path in html_files:
        report.outcomes.append(regenerate_file(html_path, db, dry_run))
    return report
