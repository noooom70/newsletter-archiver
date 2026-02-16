"""Text cleaning and chunking for search indexing."""

import re


def strip_frontmatter(markdown: str) -> str:
    """Remove YAML frontmatter (--- delimited block at start of file)."""
    return re.sub(r"\A---\n.*?\n---\n*", "", markdown, count=1, flags=re.DOTALL)


def clean_for_indexing(markdown: str) -> str:
    """Strip frontmatter, URLs, and excess whitespace for indexing."""
    text = strip_frontmatter(markdown)
    # Remove URLs
    text = re.sub(r"https?://\S+", "", text)
    # Remove markdown image/link syntax remnants
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    # Remove markdown table formatting (rows of |, ---, and cells)
    text = re.sub(r"^\|[\s\|\-]+\|$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\|", " ", text)
    # Remove markdown heading markers
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Remove bold/italic markers
    text = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", text)
    # Remove horizontal rules and leftover --- separators
    text = re.sub(r"^[\s\-]+$", "", text, flags=re.MULTILINE)
    text = re.sub(r"(?:---\s*){2,}", "", text)
    # Collapse whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def chunk_text(text: str, max_tokens: int = 256, overlap: int = 50) -> list[str]:
    """Split text into overlapping chunks for embedding.

    Uses word-level splitting as a rough token approximation.
    """
    words = text.split()
    if not words:
        return []

    chunks = []
    start = 0
    while start < len(words):
        end = start + max_tokens
        chunk = " ".join(words[start:end])
        if chunk.strip():
            chunks.append(chunk)
        if end >= len(words):
            break
        start = end - overlap

    return chunks
