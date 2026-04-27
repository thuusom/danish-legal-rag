"""
Ingestion job entry point.

This job:
1. Loads Danish law texts from the cache (seeded from in-repo JSON on first
   boot, refreshed by the live retsinformation fetcher in subsequent runs).
2. For each law, reconciles the Qdrant collection so it reflects the current
   payload exactly: every prior chunk for that ``law_code`` is deleted, the
   law is re-chunked, embedded, and upserted (Issue #23).
3. Logs a structured per-law summary line so re-ingestion deltas are visible.

EMBEDDING TIMING:
Embeddings are generated HERE, during ingestion, for each chunk.
The embedding input is LegalChunk.compute_embedding_text() which enriches
the raw paragraph text with law name and section reference.
This is NOT done at query time.

IDEMPOTENCY (Issue #23):
We use a delete-then-insert strategy scoped per ``law_code``: before
upserting the new chunk set for a law, every existing point with that
``law_code`` is deleted via a filter-based delete (so orphan IDs from
repealed paragraffer are reaped too). The window between delete and
upsert is sub-second per law and is the only "broken" period —
acceptable for v1. Cross-law deletes are never performed: re-ingesting
AFL must not touch ARL points.

An empty new payload (zero provisions for a law that already has chunks
in Qdrant) is treated as a fetch bug and refused — we do not silently
wipe a law's data.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time

from qdrant_client.models import PointStruct

# Add parent to path for shared imports
sys.path.insert(0, "/app")

from ingest.cache import list_cached_laws, seed_cache_from_repo
from ingest.chunker import chunk_law
from ingest.embedder import get_embedding_provider
from shared.admin_state import (
    write_ingestion_failed,
    write_ingestion_started,
    write_ingestion_succeeded,
)
from shared.qdrant_utils import (
    count_chunks_by_law_code,
    delete_chunks_by_law_code,
    ensure_collection,
    get_qdrant_client,
    upsert_points,
)
from shared.sparse import get_sparse_provider, is_hybrid_enabled

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def wait_for_qdrant(max_retries: int = 30, delay: float = 2.0) -> None:
    """Wait until Qdrant is ready."""
    from qdrant_client import QdrantClient
    host = os.environ.get("QDRANT_HOST", "localhost")
    port = int(os.environ.get("QDRANT_PORT", "6333"))

    for attempt in range(max_retries):
        try:
            client = QdrantClient(host=host, port=port)
            client.get_collections()
            logger.info("Qdrant is ready")
            return
        except Exception as e:
            logger.info(f"Waiting for Qdrant ({attempt+1}/{max_retries}): {e}")
            time.sleep(delay)

    raise RuntimeError("Qdrant did not become ready in time")


def _load_laws_from_cache() -> list[dict]:
    """
    Load every law JSON currently sitting in the cache directory.

    The cache is the single source of truth for ingestion (Issue #21).
    Files arrive there either via :func:`seed_cache_from_repo` (first boot,
    seeded from ``ingest/data/*.json``) or via the live retsinformation
    fetcher (Issue #20, future).
    """
    laws: list[dict] = []
    for path in list_cached_laws():
        with path.open(encoding="utf-8") as fh:
            laws.append(json.load(fh))
        logger.info(f"Loaded cached law: {path.name}")
    return laws


def run_ingestion() -> None:
    """
    Run the full ingestion pipeline against the configured Qdrant.

    Flow:
      1. Wait for Qdrant; load embedding (and optional sparse) provider.
      2. Seed the cache from in-repo JSON on first boot (idempotent).
      3. For every law in the cache:
         a. Chunk + compute stable IDs (in memory).
         b. Refuse if the new payload is empty *and* the law already has
            chunks in Qdrant — that's almost certainly a fetch bug.
         c. Delete the prior chunk set for this ``law_code`` (filter-scoped
            so cross-law data is never touched).
         d. Embed all chunks and upsert. The window between (c) and (d) is
            sub-second per law.
         e. Log a structured ``{law_code, added, deleted, total}`` line.
      4. Log run-wide totals.

    Re-ingestion is therefore fully idempotent at the law-code level:
    repealed paragraffer disappear from Qdrant on the next run without
    operator intervention (Issue #23).

    Side effect: writes ``law_cache/.ingestion_state.json`` at start, on
    success, and on failure so the admin endpoint can surface the current
    state to operators (Issue #24).
    """
    logger.info("=== Starting Danish Legal RAG Ingestion ===")
    try:
        write_ingestion_started()
    except Exception as exc:
        # Ingestion must not fail just because we couldn't write the marker.
        logger.warning(f"Could not write ingestion start marker: {exc}")
    try:
        _run_ingestion_body()
    except Exception as exc:
        try:
            write_ingestion_failed(str(exc))
        except Exception:
            logger.exception("Could not write ingestion failure marker")
        raise
    else:
        try:
            write_ingestion_succeeded()
        except Exception:
            logger.exception("Could not write ingestion success marker")


def _run_ingestion_body() -> None:
    """The original ingestion body, separated so :func:`run_ingestion` owns
    the state-marker bookkeeping without indenting the entire pipeline."""

    # Step 1: Wait for Qdrant and load providers
    wait_for_qdrant()
    qdrant = get_qdrant_client()

    embedder = get_embedding_provider()
    logger.info(f"Embedding provider: {embedder.model_name} (vector_size={embedder.vector_size})")

    ensure_collection(qdrant, embedder.vector_size)

    sparse_provider = None
    if is_hybrid_enabled():
        sparse_provider = get_sparse_provider()
        logger.info("Hybrid retrieval enabled — BM25 sparse vectors will be generated")

    # Step 2: Seed the cache (idempotent — first boot only)
    seeded = seed_cache_from_repo()
    if seeded:
        logger.info(f"Cache seeded on first boot for: {seeded}")

    # Step 3: Load law texts from the cache
    laws = _load_laws_from_cache()
    if not laws:
        raise RuntimeError(
            "Law cache is empty after seeding — check ingest/sources.yaml "
            "and the seed_file paths."
        )

    # Step 4: Per-law delete-then-insert reconciliation
    run_summary: list[dict] = []
    total_added = 0
    total_deleted = 0

    for law_data in laws:
        law_code = law_data.get("law_code")
        law_name = law_data.get("law_name", law_code or "<unknown>")

        if not law_code:
            logger.error(
                f"Skipping cache entry without law_code: {law_data.get('law_title', '?')}"
            )
            continue

        # 4a: Chunk + compute stable IDs (in memory; cheap and pure)
        chunks = chunk_law(law_data, embedding_model=embedder.model_name)

        # 4b: Refuse empty payloads if the law already has data in Qdrant.
        # This guards against fetch failures silently wiping a law.
        existing_count = count_chunks_by_law_code(qdrant, law_code)
        if not chunks and existing_count > 0:
            logger.error(
                f"Refusing to wipe law_code={law_code!r}: new payload has "
                f"0 provisions but Qdrant currently holds {existing_count} "
                f"chunks. This is almost certainly a fetch bug — leaving "
                f"existing data untouched. Check the cached JSON at "
                f"law_cache/{law_code}.json."
            )
            run_summary.append({
                "law_code": law_code,
                "added": 0,
                "deleted": 0,
                "total": existing_count,
                "status": "refused_empty",
            })
            continue

        if not chunks:
            logger.warning(
                f"Skipping {law_code}: cached JSON contains no provisions "
                f"and Qdrant has no prior data — nothing to ingest"
            )
            run_summary.append({
                "law_code": law_code,
                "added": 0,
                "deleted": 0,
                "total": 0,
                "status": "noop",
            })
            continue

        # 4c: Delete prior chunks for this law_code (filter-scoped)
        deleted = delete_chunks_by_law_code(qdrant, law_code)

        # 4d: Embed and upsert the new chunk set
        embedding_texts = [chunk.compute_embedding_text() for chunk in chunks]
        logger.info(
            f"Generating embeddings for {len(embedding_texts)} chunks of {law_name}..."
        )
        vectors = embedder.embed(embedding_texts)

        sparse_vectors = None
        if sparse_provider is not None:
            logger.info(
                f"Generating BM25 sparse vectors for {len(embedding_texts)} chunks of {law_name}..."
            )
            sparse_vectors = sparse_provider.embed(embedding_texts)

        points: list[PointStruct] = []
        for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
            vec_dict: dict = {"dense": vector}
            if sparse_vectors is not None:
                from qdrant_client.models import SparseVector
                sv = sparse_vectors[i]
                vec_dict["bm25"] = SparseVector(
                    indices=sv["indices"], values=sv["values"]
                )
            points.append(
                PointStruct(
                    id=chunk.id,
                    vector=vec_dict,
                    payload=chunk.to_qdrant_payload(),
                )
            )

        try:
            upsert_points(qdrant, points)
        except Exception:
            # Surface clearly: the delete already ran, so the law is currently
            # empty in Qdrant. The next ingestion run will re-populate it.
            logger.exception(
                f"Upsert FAILED for {law_code} after delete of {deleted} prior chunks. "
                f"Qdrant is currently MISSING {law_code} data — re-run ingestion to recover."
            )
            raise

        added = len(points)
        total_added += added
        total_deleted += deleted

        # 4e: Structured per-law summary
        logger.info(
            f"INGEST_SUMMARY law_code={law_code} added={added} "
            f"deleted={deleted} total={added}"
        )
        run_summary.append({
            "law_code": law_code,
            "added": added,
            "deleted": deleted,
            "total": added,
            "status": "ok",
        })

    # Step 5: Run-wide summary
    logger.info("=== Ingestion Complete ===")
    logger.info(
        f"INGEST_RUN_SUMMARY laws={len(run_summary)} "
        f"total_added={total_added} total_deleted={total_deleted}"
    )
    for entry in run_summary:
        logger.info(f"  {entry}")


if __name__ == "__main__":
    run_ingestion()
