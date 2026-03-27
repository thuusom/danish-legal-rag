"""
Qdrant client utilities for the Danish Legal RAG system.
"""
from __future__ import annotations
import logging
import os
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
)

logger = logging.getLogger(__name__)

COLLECTION_NAME = "danish_legal"


def get_qdrant_client() -> QdrantClient:
    """Create and return a Qdrant client using environment variables."""
    host = os.environ.get("QDRANT_HOST", "localhost")
    port = int(os.environ.get("QDRANT_PORT", "6333"))
    logger.info(f"Connecting to Qdrant at {host}:{port}")
    return QdrantClient(host=host, port=port)


def ensure_collection(client: QdrantClient, vector_size: int) -> None:
    """
    Create the Qdrant collection if it does not already exist.
    Idempotent: safe to call multiple times.
    """
    collections = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in collections:
        logger.info(f"Creating Qdrant collection '{COLLECTION_NAME}' with vector_size={vector_size}")
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )
    else:
        logger.info(f"Qdrant collection '{COLLECTION_NAME}' already exists")


def upsert_points(client: QdrantClient, points: list[PointStruct]) -> None:
    """Upsert points into the collection (idempotent by point ID)."""
    client.upsert(collection_name=COLLECTION_NAME, points=points)
    logger.info(f"Upserted {len(points)} points into '{COLLECTION_NAME}'")


def search_similar(
    client: QdrantClient,
    query_vector: list[float],
    limit: int = 5,
    filter_law: Optional[str] = None,
) -> list[dict]:
    """
    Perform semantic similarity search in Qdrant.

    The query_vector is the embedding of the user's question,
    generated at query time (not during ingestion).

    Optionally filter by law_code for more targeted retrieval.
    """
    search_filter = None
    if filter_law:
        search_filter = Filter(
            must=[FieldCondition(key="law_code", match=MatchValue(value=filter_law))]
        )

    results = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=query_vector,
        limit=limit,
        query_filter=search_filter,
        with_payload=True,
    )
    return [
        {"score": r.score, "payload": r.payload}
        for r in results
    ]


def get_all_laws(client: QdrantClient) -> list[dict]:
    """Retrieve distinct ingested laws for the /laws endpoint."""
    # Scroll through all points and collect unique laws
    seen = set()
    laws = []
    offset = None
    while True:
        records, offset = client.scroll(
            collection_name=COLLECTION_NAME,
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for record in records:
            code = record.payload.get("law_code")
            if code and code not in seen:
                seen.add(code)
                laws.append({
                    "law_code": code,
                    "law_name": record.payload.get("law_name"),
                    "law_title": record.payload.get("law_title"),
                    "law_number": record.payload.get("law_number"),
                    "source_url": record.payload.get("source_url"),
                })
        if offset is None:
            break
    return laws


def point_exists_with_hash(client: QdrantClient, point_id: str, content_hash: str) -> bool:
    """
    Check if a point with the given ID already exists AND has the same content hash.
    Used for idempotent ingestion: skip re-embedding unchanged chunks.
    """
    try:
        results = client.retrieve(
            collection_name=COLLECTION_NAME,
            ids=[point_id],
            with_payload=True,
        )
        if results:
            existing_hash = results[0].payload.get("embedding_content_hash")
            return existing_hash == content_hash
    except Exception:
        pass
    return False
