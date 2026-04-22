"""
BM25 sparse vector provider for hybrid search.

Uses fastembed's Qdrant/bm25 model to generate sparse vectors suitable for
Qdrant's native sparse vector support.  These are combined with dense vectors
via Reciprocal Rank Fusion (RRF) at query time.

The same provider is used at ingestion AND query time to ensure consistency.
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)


class BM25SparseProvider:
    """
    Sparse vector provider backed by fastembed's Qdrant/bm25 model.

    Returns SparseVector-compatible dicts with 'indices' and 'values' keys,
    which map directly to qdrant_client.models.SparseVector.
    """

    def __init__(self, model_name: str = "Qdrant/bm25") -> None:
        from fastembed import SparseTextEmbedding

        self._model_name = model_name
        logger.info(f"Loading BM25 sparse model: {model_name}")
        self._model = SparseTextEmbedding(model_name=model_name)
        logger.info("BM25 sparse model loaded")

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed(self, texts: list[str]) -> list[dict]:
        """
        Generate sparse vectors for a list of texts.

        Returns list of dicts, each with:
          - indices: list[int]  (token IDs with non-zero weight)
          - values:  list[float] (corresponding BM25 weights)
        """
        results = list(self._model.embed(texts))
        return [
            {"indices": r.indices.tolist(), "values": r.values.tolist()}
            for r in results
        ]

    def embed_single(self, text: str) -> dict:
        """Convenience: sparse vector for a single text."""
        return self.embed([text])[0]


def is_hybrid_enabled(override: Optional[str] = None) -> bool:
    """
    Check whether hybrid retrieval is active.

    Resolution order:
    1. Per-request override (from AskRequest.retrieval_strategy / SearchRequest.retrieval_strategy)
    2. RETRIEVAL_STRATEGY env var
    3. Default: "dense" (hybrid OFF)
    """
    strategy = override or os.environ.get("RETRIEVAL_STRATEGY", "dense")
    return strategy.lower() == "hybrid"


@lru_cache(maxsize=1)
def get_sparse_provider() -> BM25SparseProvider:
    """Cached singleton sparse provider. Only loaded when hybrid is first needed."""
    return BM25SparseProvider()
