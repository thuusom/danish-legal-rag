"""
Embedding provider for the API service.

This module handles query-time embedding:
When a user submits a question, it is embedded here using the SAME model
that was used during ingestion. The resulting vector is used for
Qdrant similarity search.

The embedding model is configured via EMBEDDING_PROVIDER env var,
same as in ingest/embedder.py, to ensure consistency.
"""
from __future__ import annotations
import logging
import os
from functools import lru_cache

logger = logging.getLogger(__name__)


class QueryEmbedder:
    """
    Generates query-time embeddings for user questions.
    Uses the same model as ingestion to ensure vector space consistency.
    """

    def __init__(self) -> None:
        self._provider = _load_provider()
        self.model_name = self._provider.model_name
        self.vector_size = self._provider.vector_size
        logger.info(f"Query embedder ready: {self.model_name}")

    def embed_query(self, text: str) -> list[float]:
        """
        QUERY EMBEDDING STEP:
        This is called at search time, NOT during ingestion.
        The user's natural language question is embedded here,
        then compared against chunk embeddings in Qdrant.
        """
        logger.info(f"Embedding query: '{text[:80]}...' " if len(text) > 80 else f"Embedding query: '{text}'")
        return self._provider.embed_single(text)


def _load_provider():
    """Load embedding provider (mirrors ingest/embedder.py)."""
    provider = os.environ.get("EMBEDDING_PROVIDER", "sentence-transformers").lower()

    if provider == "openai":
        from ingest.embedder import OpenAIEmbeddingProvider
        model = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        return OpenAIEmbeddingProvider(model_name=model)
    else:
        from ingest.embedder import SentenceTransformersProvider
        model = os.environ.get("ST_MODEL_NAME", "paraphrase-multilingual-mpnet-base-v2")
        return SentenceTransformersProvider(model_name=model)


@lru_cache(maxsize=1)
def get_query_embedder() -> QueryEmbedder:
    """Cached singleton embedder (loaded once at startup)."""
    return QueryEmbedder()
