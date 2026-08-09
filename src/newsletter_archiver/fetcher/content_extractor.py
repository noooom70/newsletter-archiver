"""HTML cleanup and Markdown conversion."""

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup
from markdownify import markdownify

from newsletter_archiver.fetcher.link_cleaner import clean_links

_CHROME_PATTERNS = [
    re.compile(r"unsubscribe", re.IGNORECASE),
    re.compile(r"manage\s+(your\s+)?preferences", re.IGNORECASE),
    re.compile(r"email\s+preferences", re.IGNORECASE),
    re.compile(r"view\s+(this\s+)?(email\s+)?(online|in\s+(your\s+)?browser)", re.IGNORECASE),
    re.compile(r"privacy\s+policy", re.IGNORECASE),
    re.compile(r"terms\s*(&(amp;)?|and)\s*conditions", re.IGNORECASE),
    re.compile(r"contact\s+us", re.IGNORECASE),
    re.compile(r"about\s+us", re.IGNORECASE),
    re.compile(r"forward\s+to\s+a\s+friend", re.IGNORECASE),
    re.compile(r"update\s+your\s+(details|profile|preferences)", re.IGNORECASE),
]

_BOILERPLATE_PATTERNS = [
    re.compile(r"this email (was|has been) sent to", re.IGNORECASE),
    re.compile(r"registered in england and wales", re.IGNORECASE),
    re.compile(r"copyright © .* all rights reserved", re.IGNORECASE),
]

_ALT_BOILERPLATE = {"logo", "spacer", "divider", "banner", "image", "photo", "icon"}
_IMAGE_FILE_RE = re.compile(r"\.(png|jpe?g|gif|webp|svg)\s*$", re.IGNORECASE)


def _meaningful_alt(alt: str) -> bool:
    alt = alt.strip()
    return (
        len(alt.split()) >= 3
        and "://" not in alt
        and not _IMAGE_FILE_RE.search(alt)
        and alt.lower() not in _ALT_BOILERPLATE
    )


def _preserve_alt_text(soup) -> None:
    """Replace images that carry meaningful alt text with that text."""
    for img in soup.find_all("img"):
        alt = img.get("alt", "")
        if _meaningful_alt(alt):
            img.replace_with(alt.strip())


_BLOCK_TAGS = ["p", "div", "table", "img", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6"]


def _own(table, tag_names):
    """Descendant tags whose nearest table ancestor is this table."""
    return [t for t in table.find_all(tag_names) if t.find_parent("table") is table]


def _is_data_table(table) -> bool:
    if _own(table, ["th"]):
        return True
    rows = _own(table, ["tr"])
    if len(rows) < 2:
        return False
    for tr in rows:
        cells = [td for td in tr.find_all("td") if td.find_parent("table") is table]
        if len(cells) < 2:
            return False
        for td in cells:
            if td.find(_BLOCK_TAGS) or len(td.get_text(strip=True)) >= 80:
                return False
    return True


def _flatten_layout_tables(soup) -> None:
    """Flatten layout tables to divs; leave data tables for markdownify."""
    for table in reversed(soup.find_all("table")):
        if _is_data_table(table):
            continue
        for section in _own(table, ["thead", "tbody", "tfoot"]):
            section.unwrap()
        for cell in _own(table, ["tr", "td", "th"]):
            cell.name = "div"
        table.name = "div"


def _remove_chrome(soup) -> None:
    """Remove chrome links (unsubscribe/footer/nav) and their small parents."""
    for a_tag in soup.find_all("a"):
        text = a_tag.get_text(strip=True)
        if any(p.search(text) for p in _CHROME_PATTERNS):
            parent = a_tag.parent
            if parent and parent.name in ("p", "div", "td", "span"):
                if len(parent.get_text(strip=True)) < 200:
                    parent.decompose()
                    continue
            a_tag.decompose()


def _remove_boilerplate(soup) -> None:
    """Remove small blocks matching known sender-footer boilerplate."""
    # Innermost first (like _flatten_layout_tables): a boilerplate line
    # decomposed from inside-out won't cause its outer wrapper (which may
    # also hold genuine content) to spuriously match on the same pattern.
    for tag in reversed(soup.find_all(["p", "td", "div", "span"])):
        text = tag.get_text(" ", strip=True)
        if len(text) < 300 and any(p.search(text) for p in _BOILERPLATE_PATTERNS):
            tag.decompose()


@dataclass
class ExtractionResult:
    markdown: str
    unwrap_failures: int


def _remove_tracking_pixels(soup) -> None:
    """Remove 1x1 / hidden images (extracted verbatim from the old clean_html)."""
    for img in soup.find_all("img"):
        width = img.get("width", "")
        height = img.get("height", "")
        style = img.get("style", "")
        is_tracking = (
            (width == "1" and height == "1")
            or "display:none" in style.replace(" ", "")
            or "visibility:hidden" in style.replace(" ", "")
            or (width == "0" or height == "0")
        )
        if is_tracking:
            img.decompose()


def _clean_tree(soup) -> int:
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()
    _remove_tracking_pixels(soup)
    failures = clean_links(soup)
    _remove_chrome(soup)
    _remove_boilerplate(soup)
    _preserve_alt_text(soup)
    _flatten_layout_tables(soup)
    return failures


def clean_html(html: str) -> str:
    """Remove tracking pixels, scripts, styles, and other noise from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    _clean_tree(soup)
    return str(soup)


def extract_markdown(html: str) -> ExtractionResult:
    """Convert cleaned HTML to Markdown, returning the result and unwrap stats."""
    soup = BeautifulSoup(html, "html.parser")
    failures = _clean_tree(soup)
    md = markdownify(str(soup), heading_style="ATX", strip=["img"])
    md = strip_invisible_chars(md)
    md = re.sub(r"\[\s*\]\([^)]*\)", "", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return ExtractionResult(md.strip(), failures)


def strip_invisible_chars(text: str) -> str:
    """Remove invisible Unicode characters used as email preheader padding.

    Common offenders: zero-width spaces, soft hyphens, combining grapheme
    joiners, and other zero-width/formatting characters.
    """
    # U+00AD soft hyphen, U+034F combining grapheme joiner,
    # U+200B-U+200F zero-width spaces/joiners, U+2060-U+2064 word joiners,
    # U+FEFF byte order mark
    text = re.sub(r"[\u00ad\u034f\u200b-\u200f\u2060-\u2064\ufeff]", "", text)
    # Collapse runs of whitespace left behind
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text


def html_to_markdown(html: str) -> str:
    """Convert cleaned HTML to Markdown."""
    return extract_markdown(html).markdown


def build_markdown_document(
    subject: str,
    sender_name: str,
    sender_email: str,
    received_date: str,
    markdown_body: str,
) -> str:
    """Build a complete Markdown document with frontmatter."""
    frontmatter = f"""---
title: "{subject}"
from: "{sender_name} <{sender_email}>"
date: {received_date}
---

"""
    return frontmatter + markdown_body


def calculate_word_count(text: str) -> int:
    """Count words in text."""
    return len(text.split())


def calculate_reading_time(word_count: int, wpm: int = 200) -> float:
    """Estimate reading time in minutes."""
    return round(word_count / wpm, 1)
