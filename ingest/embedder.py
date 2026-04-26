"""
Embedding provider for the ingestion pipeline.

This module is responsible for:
1. Loading the embedding model (or connecting to the embedding API)
2. Generating embeddings for each LegalChunk during ingestion
3. Supporting multiple embedding providers via EMBEDDING_PROVIDER env var

Embedding strategy:
- We embed an ENRICHED version of the text that includes law name and section reference.
- This improves semantic matching for both content-based and reference-based queries.
- The raw reference fields are stored SEPARATELY in the Qdrant payload.
- See LegalChunk.compute_embedding_text() for the exact embedding input.

Providers:
- 'sentence-transformers' (default, offline): paraphrase-multilingual-mpnet-base-v2
- 'openai': text-embedding-3-small via OpenAI API
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Name of the embedding model."""
        ...

    @property
    @abstractmethod
    def vector_size(self) -> int:
        """Dimension of the output vectors."""
        ...

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        ...

    def embed_single(self, text: str) -> list[float]:
        """Convenience method for single text embedding."""
        return self.embed([text])[0]


class SentenceTransformersProvider(EmbeddingProvider):
    """
    Local embedding via sentence-transformers.
    Uses paraphrase-multilingual-mpnet-base-v2 which supports Danish.
    Vector size: 768.
    No API key required.
    """

    def __init__(self, model_name: str = "paraphrase-multilingual-mpnet-base-v2"):
        from sentence_transformers import SentenceTransformer
        self._model_name = model_name
        logger.info(f"Loading sentence-transformers model: {model_name}")
        self._model = SentenceTransformer(model_name)
        logger.info("Model loaded successfully")

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def vector_size(self) -> int:
        return 768

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings. Called during ingestion AND at query time."""
        embeddings = self._model.encode(texts, normalize_embeddings=True)
        return [emb.tolist() for emb in embeddings]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """
    OpenAI embeddings via API.
    Requires OPENAI_API_KEY environment variable.
    Vector size: 1536 (text-embedding-3-small) or 3072 (text-embedding-3-large).
    """

    def __init__(self, model_name: str = "text-embedding-3-small"):
        import openai
        self._model_name = model_name
        self._client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self._vector_size = 1536 if "small" in model_name else 3072
        logger.info(f"Using OpenAI embedding model: {model_name}")

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def vector_size(self) -> int:
        return self._vector_size

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(input=texts, model=self._model_name)
        return [item.embedding for item in response.data]


def get_embedding_provider() -> EmbeddingProvider:
    """
    Factory function. Returns the configured embedding provider.

    Set EMBEDDING_PROVIDER=openai to use OpenAI.
    Default is sentence-transformers (local, no API key needed).
    """
    provider = os.environ.get("EMBEDDING_PROVIDER", "sentence-transformers").lower()

    if provider == "openai":
        model = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        return OpenAIEmbeddingProvider(model_name=model)
    else:
        model = os.environ.get(
            "ST_MODEL_NAME",
            "paraphrase-multilingual-mpnet-base-v2"
        )
        return SentenceTransformersProvider(model_name=model)
