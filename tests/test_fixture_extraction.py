"""Structural regression tests over sanitized per-publication fixtures.

Fixtures are fully synthetic (see leak-check test) but reproduce each
publication's real HTML motifs: SafeLink wrapping, layout-table nesting,
chrome links, boilerplate footers.
"""

from pathlib import Path

import pytest

from newsletter_archiver.fetcher.content_extractor import extract_markdown

FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURES = sorted(FIXTURE_DIR.glob("*.html"))

# Content that must SURVIVE extraction, per fixture stem.
MUST_KEEP = {
    "stratechery": ["Aggregators and Everything Else", "demand aggregation",
                    "https://stratechery.example/2026/example-essay/",
                    "Chart comparing aggregator margins"],
    "the_diff": ["Strangely Reflexive", "market microstructure",
                 "https://thediff.example/p/example-post"],
    "the_economist": ["The world in brief", "Catch up quickly",
                      "Second teaser", "https://click.economist.example/"],
    "the_new_yorker": ["The Lab Studying", "may not be measurable",
                       "Illustration of a research laboratory"],
}

FORBIDDEN_IN_OUTPUT = [
    "safelinks.protection.outlook.com",
    "access_token",
    "?qs=", "&qs=",
    "reader@example.com",
    "Unsubscribe", "Privacy Policy", "| --- |",
]

FORBIDDEN_IN_FIXTURES = ["dannewman", "@outlook.com", "eyJhbGciOi"]


def test_fixtures_exist():
    assert {f.stem for f in FIXTURES} == set(MUST_KEEP)


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.stem)
def test_fixtures_contain_no_real_pii(fixture):
    text = fixture.read_text(encoding="utf-8")
    for needle in FORBIDDEN_IN_FIXTURES:
        assert needle not in text, f"{fixture.name} leaks {needle!r}"


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.stem)
def test_extraction_keeps_content_drops_noise(fixture):
    result = extract_markdown(fixture.read_text(encoding="utf-8"))
    for needle in MUST_KEEP[fixture.stem]:
        assert needle in result.markdown, f"lost content: {needle!r}"
    for needle in FORBIDDEN_IN_OUTPUT:
        assert needle not in result.markdown, f"noise survived: {needle!r}"
    assert result.unwrap_failures == 0
