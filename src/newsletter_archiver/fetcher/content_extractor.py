"""HTML cleanup and Markdown conversion."""

import re

from bs4 import BeautifulSoup
from markdownify import markdownify


def clean_html(html: str) -> str:
    """Remove tracking pixels, scripts, styles, and other noise from HTML."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove script and style tags
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()

    # Remove tracking pixels (1x1 images, hidden images)
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

    # Remove common unsubscribe/footer sections
    footer_patterns = [
        re.compile(r"unsubscribe", re.IGNORECASE),
        re.compile(r"manage\s+(your\s+)?preferences", re.IGNORECASE),
        re.compile(r"email\s+preferences", re.IGNORECASE),
        re.compile(r"view\s+(this\s+)?(email\s+)?in\s+(your\s+)?browser", re.IGNORECASE),
    ]

    # Only remove links/small sections matching footer patterns, not large blocks
    for a_tag in soup.find_all("a"):
        text = a_tag.get_text(strip=True)
        if any(p.search(text) for p in footer_patterns):
            # Remove the parent <p> or <div> if it's small
            parent = a_tag.parent
            if parent and parent.name in ("p", "div", "td", "span"):
                parent_text = parent.get_text(strip=True)
                if len(parent_text) < 200:
                    parent.decompose()
                    continue
            a_tag.decompose()

    return str(soup)


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
    cleaned = clean_html(html)
    md = markdownify(cleaned, heading_style="ATX", strip=["img"])

    # Strip invisible email preheader padding
    md = strip_invisible_chars(md)

    # Clean up excessive whitespace
    md = re.sub(r"\n{3,}", "\n\n", md)
    md = md.strip()

    return md


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
