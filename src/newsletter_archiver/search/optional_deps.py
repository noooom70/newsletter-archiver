"""Availability check for the optional 'rag' extra (semantic search + RAG Q&A)."""

from importlib.util import find_spec

RAG_MODULES = ("numpy", "sentence_transformers", "anthropic")

RAG_INSTALL_HINT = (
    "Semantic search and RAG Q&A require the optional 'rag' extra.\n"
    "Install with: poetry install --extras rag  "
    "(or: pip install 'newsletter-archiver[rag]')"
)


def rag_available() -> bool:
    """True if all dependencies of the 'rag' extra are importable."""
    return all(find_spec(m) is not None for m in RAG_MODULES)
