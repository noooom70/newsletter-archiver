"""RAG Q&A search: retrieve relevant chunks and answer questions via Claude."""

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Generator

import anthropic

from newsletter_archiver.core.config import get_settings
from newsletter_archiver.search.vector import ChunkResult, VectorSearchManager

SYSTEM_PROMPT = (
    "You are a research assistant that answers questions using a newsletter archive. "
    "Use ONLY the provided newsletter excerpts to answer. Cite sources by [title, date]. "
    "If the excerpts don't contain enough information, say so."
)


@dataclass
class AskResult:
    sources: list[dict] = field(default_factory=list)
    stream: Generator[str, None, None] | None = None


def _build_user_prompt(chunks: list[ChunkResult], question: str) -> str:
    """Assemble retrieved chunks and question into a prompt."""
    parts = ["## Newsletter excerpts\n"]
    for chunk in chunks:
        parts.append(
            f'### "{chunk.subject}" — {chunk.sender_name} ({chunk.date})\n'
            f"{chunk.chunk_text}\n"
        )
    parts.append(f"## Question\n{question}")
    return "\n".join(parts)


def _deduplicate_sources(chunks: list[ChunkResult]) -> list[dict]:
    """Return unique newsletters from chunks, preserving order of first appearance."""
    seen: OrderedDict[int, dict] = OrderedDict()
    for chunk in chunks:
        if chunk.newsletter_id not in seen:
            seen[chunk.newsletter_id] = {
                "subject": chunk.subject,
                "sender_name": chunk.sender_name,
                "date": chunk.date,
            }
    return list(seen.values())


def _stream_response(
    client: anthropic.Anthropic,
    model: str,
    user_prompt: str,
) -> Generator[str, None, None]:
    """Stream Claude's response text."""
    with client.messages.stream(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        for text in stream.text_stream:
            yield text


def ask(
    question: str,
    db_manager,
    top_k: int = 10,
    sender: str | None = None,
    model: str | None = None,
) -> AskResult:
    """Ask a question over the archive using RAG.

    Returns an AskResult with sources and a streaming generator.
    """
    settings = get_settings()

    if not settings.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Export it as an environment variable "
            "or add it to your .env file."
        )

    model = model or settings.anthropic_model

    # Retrieve relevant chunks
    vm = VectorSearchManager()
    chunks = vm.search_chunks(question, db_manager, top_k=top_k, sender=sender)

    if not chunks:
        return AskResult()

    sources = _deduplicate_sources(chunks)
    user_prompt = _build_user_prompt(chunks, question)
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    return AskResult(
        sources=sources,
        stream=_stream_response(client, model, user_prompt),
    )
