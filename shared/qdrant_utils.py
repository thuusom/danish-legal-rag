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
    FieldCondition,
    Filter,
    FilterSelector,
    Fusion,
    FusionQuery,
    MatchValue,
    PointStruct,
    Prefetch,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

logger = logging.getLogger(__name__)

COLLECTION_NAME = "danish_legal"


def get_qdrant_client() -> QdrantClient:
    """Create and return a Qdrant client using environment variables."""
    host = os.environ.get("QDRANT_HOST", "localhost")
    port = int(os.environ.get("QDRANT_PORT", "6333"))
    logger.info(f"Connecting to Qdrant at {host}:{port}")
    return QdrantClient(host=host, port=port)


def _want_sparse() -> bool:
    """Check if the current config expects sparse vectors (hybrid mode)."""
    return os.environ.get("RETRIEVAL_STRATEGY", "dense").lower() == "hybrid"


def ensure_collection(client: QdrantClient, vector_size: int) -> None:
    """
    Create the Qdrant collection if it does not already exist.
    Uses named vectors: ``"dense"`` for the embedding vector.
    When RETRIEVAL_STRATEGY=hybrid, also configures a ``"bm25"`` sparse vector.

    If the collection already exists, validates that its sparse config
    matches expectations. A mismatch raises RuntimeError so stale data
    is never silently mixed with a new schema.

    Idempotent: safe to call multiple times with the same config.
    """
    want_sparse = _want_sparse()

    collections = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in collections:
        sparse_config = {}
        if want_sparse:
            sparse_config = {"bm25": SparseVectorParams()}
            logger.info(
                f"Creating collection '{COLLECTION_NAME}' with dense({vector_size}) + sparse(bm25)"
            )
        else:
            logger.info(
                f"Creating collection '{COLLECTION_NAME}' with dense({vector_size})"
            )

        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={"dense": VectorParams(size=vector_size, distance=Distance.COSINE)},
            sparse_vectors_config=sparse_config if sparse_config else None,
        )
    else:
        # Validate schema matches expectations
        info = client.get_collection(COLLECTION_NAME)
        has_sparse = (
            info.config.params.sparse_vectors is not None
            and "bm25" in (info.config.params.sparse_vectors or {})
        )
        if want_sparse and not has_sparse:
            raise RuntimeError(
                f"Collection '{COLLECTION_NAME}' exists with sparse=False but config expects "
                f"sparse=True. Run: docker compose down -v && docker compose up --build"
            )
        if not want_sparse and has_sparse:
            # Tolerate: collection has sparse but we only need dense.
            # Dense-only queries will simply ignore the sparse index.
            logger.info(
                f"Collection '{COLLECTION_NAME}' has sparse vectors but running in dense mode "
                f"(this is fine; sparse index is unused)"
            )
        else:
            logger.info(f"Qdrant collection '{COLLECTION_NAME}' already exists, schema OK")


def upsert_points(client: QdrantClient, points: list[PointStruct]) -> None:
    """Upsert points into the collection (idempotent by point ID)."""
    client.upsert(collection_name=COLLECTION_NAME, points=points)
    logger.info(f"Upserted {len(points)} points into '{COLLECTION_NAME}'")


def search_similar(
    client: QdrantClient,
    query_vector: list[float],
    limit: int = 5,
    filter_law: Optional[str] = None,
    sparse_vector: Optional[dict] = None,
) -> list[dict]:
    """
    Perform similarity search in Qdrant.

    When *sparse_vector* is provided, runs hybrid retrieval:
    two prefetch legs (dense + BM25 sparse) fused via Reciprocal Rank
    Fusion (RRF) server-side.  Otherwise, plain dense search on the
    ``"dense"`` named vector.

    Uses query_points() (qdrant-client >= 1.10).
    """
    search_filter = None
    if filter_law:
        search_filter = Filter(
            must=[FieldCondition(key="law_code", match=MatchValue(value=filter_law))]
        )

    if sparse_vector is not None:
        # Hybrid: prefetch dense + sparse, fuse with RRF
        prefetch_limit = limit * 3  # over-fetch each leg for better fusion
        sparse_qvec = SparseVector(
            indices=sparse_vector["indices"],
            values=sparse_vector["values"],
        )
        logger.info(
            f"Hybrid search: dense prefetch={prefetch_limit}, "
            f"sparse terms={len(sparse_vector['indices'])}, final limit={limit}"
        )
        response = client.query_points(
            collection_name=COLLECTION_NAME,
            prefetch=[
                Prefetch(query=query_vector, using="dense", limit=prefetch_limit),
                Prefetch(query=sparse_qvec, using="bm25", limit=prefetch_limit),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            limit=limit,
            query_filter=search_filter,
            with_payload=True,
        )
    else:
        # Dense only — query the named "dense" vector
        response = client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            using="dense",
            limit=limit,
            query_filter=search_filter,
            with_payload=True,
        )

    return [
        {"score": r.score, "payload": r.payload}
        for r in response.points
    ]


def get_all_laws(client: QdrantClient) -> list[dict]:
    """
    Retrieve distinct ingested laws for the /laws endpoint.

    For each law, also aggregate the Issue #22 provenance fields across its
    chunks: ``eli`` and ``law_version_date`` use first-non-null wins
    (chunks of the same law share these), and ``latest_ingested_at`` is the
    maximum ``ingested_at`` value seen.
    """
    # Scroll through all points and aggregate by law_code
    by_code: dict[str, dict] = {}
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
            if not code:
                continue
            if code not in by_code:
                by_code[code] = {
                    "law_code": code,
                    "law_name": record.payload.get("law_name"),
                    "law_title": record.payload.get("law_title"),
                    "law_number": record.payload.get("law_number"),
                    "source_url": record.payload.get("source_url"),
                    "eli": record.payload.get("eli"),
                    "law_version_date": record.payload.get("law_version_date"),
                    "latest_ingested_at": record.payload.get("ingested_at"),
                }
            else:
                entry = by_code[code]
                # First-non-null wins for static fields
                if entry.get("eli") is None and record.payload.get("eli"):
                    entry["eli"] = record.payload.get("eli")
                if entry.get("law_version_date") is None and record.payload.get("law_version_date"):
                    entry["law_version_date"] = record.payload.get("law_version_date")
                # Max wins for ingested_at (ISO-8601 strings sort lexicographically when same TZ)
                ts = record.payload.get("ingested_at")
                if ts and (entry.get("latest_ingested_at") is None or ts > entry["latest_ingested_at"]):
                    entry["latest_ingested_at"] = ts
        if offset is None:
            break
    return list(by_code.values())


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


def count_chunks_by_law_code(client: QdrantClient, law_code: str) -> int:
    """
    Count points in the collection whose ``payload.law_code == law_code``.

    Uses the dedicated Qdrant ``count`` API with an exact filter — never
    a global count.

    Returns 0 if the collection does not yet exist.
    """
    try:
        flt = Filter(
            must=[FieldCondition(key="law_code", match=MatchValue(value=law_code))]
        )
        result = client.count(
            collection_name=COLLECTION_NAME,
            count_filter=flt,
            exact=True,
        )
        return int(result.count)
    except Exception as exc:
        logger.warning(
            f"count_chunks_by_law_code({law_code!r}) failed; assuming 0: {exc}"
        )
        return 0


def delete_chunks_by_law_code(client: QdrantClient, law_code: str) -> int:
    """
    Delete every point whose ``payload.law_code == law_code``.

    Scoped strictly by ``law_code`` filter — never global. Used for
    idempotent re-ingestion of a single law (Issue #23): remove the prior
    chunk set before upserting the new one so deletions in the upstream
    source are reflected in Qdrant.

    The deletion is filter-based (rather than ID-based) so it also reaps
    any orphan chunks whose stable IDs are no longer produced by the
    current chunker — for example a paragraph that was repealed upstream.

    Returns:
        The number of points present for ``law_code`` *before* the delete,
        as observed via :func:`count_chunks_by_law_code`. Useful for the
        structured ``deleted=N`` log line on each run. Returns 0 when the
        collection does not exist yet (first-ever ingestion).
    """
    if not law_code:
        raise ValueError("law_code must be a non-empty string")

    before = count_chunks_by_law_code(client, law_code)
    if before == 0:
        logger.info(
            f"No existing chunks for law_code={law_code!r}; nothing to delete"
        )
        return 0

    flt = Filter(
        must=[FieldCondition(key="law_code", match=MatchValue(value=law_code))]
    )
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=FilterSelector(filter=flt),
        wait=True,
    )
    logger.info(
        f"Deleted {before} chunks for law_code={law_code!r} from '{COLLECTION_NAME}'"
    )
    return before
