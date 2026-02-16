"""Vector similarity search using sentence-transformers and NumPy."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from newsletter_archiver.core.config import get_settings
from newsletter_archiver.search.chunker import chunk_text, clean_for_indexing


MODEL_NAME = "all-MiniLM-L6-v2"


@dataclass
class VectorResult:
    newsletter_id: int
    subject: str
    sender_name: str
    date: str
    score: float
    snippet: str


class VectorSearchManager:
    def __init__(self):
        settings = get_settings()
        self.embeddings_path = settings.local_dir / "data" / "embeddings.npz"
        self._model = None
        self._embeddings: np.ndarray | None = None
        self._chunk_ids: list[tuple[int, int]] | None = None  # (newsletter_id, chunk_index)
        self._load_embeddings()

    def _load_embeddings(self) -> None:
        """Load stored embeddings from disk if they exist."""
        if self.embeddings_path.exists():
            data = np.load(self.embeddings_path, allow_pickle=True)
            self._embeddings = data["embeddings"]
            self._chunk_ids = [(int(x[0]), int(x[1])) for x in data["chunk_ids"]]
        else:
            self._embeddings = None
            self._chunk_ids = []

    @property
    def model(self):
        """Lazy-load the sentence-transformers model."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(MODEL_NAME)
        return self._model

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        """Generate embeddings for a list of texts."""
        return self.model.encode(texts, show_progress_bar=False, convert_to_numpy=True)

    def index_newsletter(self, newsletter_id: int, content: str, db_manager) -> None:
        """Chunk, embed, and store a newsletter's content."""
        chunks = chunk_text(content)
        if not chunks:
            return

        # Save chunk texts to DB for later retrieval
        db_manager.save_embedding_chunks(newsletter_id, chunks)

        # Generate embeddings
        new_embeddings = self.embed_texts(chunks)
        new_ids = [(newsletter_id, i) for i in range(len(chunks))]

        # Remove any existing embeddings for this newsletter
        if self._embeddings is not None and len(self._chunk_ids) > 0:
            keep = [i for i, (nid, _) in enumerate(self._chunk_ids) if nid != newsletter_id]
            if len(keep) < len(self._chunk_ids):
                self._embeddings = self._embeddings[keep]
                self._chunk_ids = [self._chunk_ids[i] for i in keep]

        # Append new embeddings
        if self._embeddings is not None and len(self._embeddings) > 0:
            self._embeddings = np.vstack([self._embeddings, new_embeddings])
        else:
            self._embeddings = new_embeddings
        self._chunk_ids.extend(new_ids)

    def save(self) -> None:
        """Persist embeddings to disk."""
        if self._embeddings is not None and len(self._chunk_ids) > 0:
            self.embeddings_path.parent.mkdir(parents=True, exist_ok=True)
            np.savez(
                self.embeddings_path,
                embeddings=self._embeddings,
                chunk_ids=np.array(self._chunk_ids),
            )

    def clear(self) -> None:
        """Remove all stored embeddings."""
        if self.embeddings_path.exists():
            self.embeddings_path.unlink()
        self._embeddings = None
        self._chunk_ids = []

    def search(self, query: str, db_manager, top_k: int = 20,
               sender: str | None = None) -> list[VectorResult]:
        """Find newsletters most similar to the query."""
        if self._embeddings is None or len(self._chunk_ids) == 0:
            return []

        query_embedding = self.embed_texts([query])[0]

        # Cosine similarity (embeddings are already normalized by sentence-transformers)
        similarities = np.dot(self._embeddings, query_embedding)

        # Get top chunk matches
        top_indices = np.argsort(similarities)[::-1]

        # Deduplicate by newsletter_id, keeping best score per newsletter
        seen = set()
        results = []
        for idx in top_indices:
            nid, chunk_idx = self._chunk_ids[idx]
            if nid in seen:
                continue
            seen.add(nid)

            newsletter = db_manager.get_newsletter_by_id(nid)
            if newsletter is None:
                continue

            if sender and sender.lower() not in (newsletter.sender_name or "").lower():
                continue

            # Get the chunk text for snippet
            chunks = db_manager.get_embedding_chunks(nid)
            snippet = ""
            for c in chunks:
                if c.chunk_index == chunk_idx:
                    snippet = c.chunk_text[:200]
                    break

            date_str = newsletter.received_date.strftime("%Y-%m-%d") if newsletter.received_date else ""
            results.append(VectorResult(
                newsletter_id=nid,
                subject=newsletter.subject,
                sender_name=newsletter.sender_name or "",
                date=date_str,
                score=float(similarities[idx]),
                snippet=snippet,
            ))

            if len(results) >= top_k:
                break

        return results

    def get_indexed_ids(self, db_manager) -> set[int]:
        """Get newsletter IDs that have embeddings stored."""
        return db_manager.get_newsletter_ids_with_chunks()
