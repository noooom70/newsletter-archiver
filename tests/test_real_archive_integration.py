"""Integration checks against the real archive. Auto-skipped when absent (CI)."""

from pathlib import Path

import pytest

from newsletter_archiver.fetcher.content_extractor import extract_markdown

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
