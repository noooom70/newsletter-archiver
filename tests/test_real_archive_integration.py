"""Integration checks against the real archive. Auto-skipped when absent (CI)."""

import os
from pathlib import Path

import pytest

from newsletter_archiver.fetcher.content_extractor import extract_markdown
from newsletter_archiver.storage.regenerator import split_frontmatter

REAL_ARCHIVE = Path(
    "/mnt/c/Users/danne/Proton Drive/noomonics/My files/Projects/"
    "newsletter-archive/archives"
)

pytestmark = pytest.mark.skipif(
    not REAL_ARCHIVE.exists(), reason="real archive not present (CI-safe skip)"
)

PUBLICATIONS = ["stratechery", "the-diff", "the-economist", "the-new-yorker"]


def _one_sample(pub: str) -> Path:
    files = sorted((REAL_ARCHIVE / "2026" / "02" / pub).glob("*.html"))
    assert files, f"no stored html for {pub}"
    return files[0]


@pytest.mark.parametrize("pub", PUBLICATIONS)
def test_real_extraction_invariants(pub):
    html = _one_sample(pub).read_text(encoding="utf-8", errors="replace")
    result = extract_markdown(html)
    md = result.markdown

    assert "safelinks.protection.outlook.com" not in md
    assert "access_token=" not in md
    assert "?qs=" not in md and "&qs=" not in md
    assert "| --- | --- |" not in md
    assert result.unwrap_failures == 0
    assert len(md) > 200, "over-stripped: nearly nothing survived"
    assert len(md) < len(html), "output should shrink"


@pytest.mark.parametrize("pub", PUBLICATIONS)
def test_owner_address_absent_from_extraction(pub):
    """The mailbox owner's address must not survive into the retrieval copy.

    The address itself is never written here — the repo is public. The local
    runner supplies it via the NEWSLETTER_OWNER_EMAIL environment variable
    (e.g. `NEWSLETTER_OWNER_EMAIL=you@example.com poetry run pytest`); the
    check is skipped when the variable is unset.
    """
    owner = os.environ.get("NEWSLETTER_OWNER_EMAIL", "").strip()
    if not owner:
        pytest.skip("NEWSLETTER_OWNER_EMAIL not set")
    md = extract_markdown(
        _one_sample(pub).read_text(encoding="utf-8", errors="replace")
    ).markdown
    assert owner.lower() not in md.lower()


@pytest.mark.parametrize("pub", PUBLICATIONS)
def test_paired_markdown_frontmatter_intact(pub):
    """Every sampled .html has a paired .md whose frontmatter still parses.

    Read-only: regeneration preserves the frontmatter block verbatim, so a
    file that no longer splits would mean metadata drift on disk.
    """
    md_path = _one_sample(pub).with_suffix(".md")
    assert md_path.exists(), f"no paired .md for {pub}"
    assert split_frontmatter(md_path.read_text(encoding="utf-8", errors="replace")) is not None
