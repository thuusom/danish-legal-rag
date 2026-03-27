"""
Ingestion job entry point.

This job:
1. Loads Danish law texts (from retsinformation.dk or local fallback)
2. Chunks each law into LegalChunk objects (one per provision/§)
3. Generates embeddings for each chunk
4. Upserts into Qdrant (idempotent: skips unchanged chunks)

EMBEDDING TIMING:
Embeddings are generated HERE, during ingestion, for each chunk.
The embedding input is LegalChunk.compute_embedding_text() which enriches
the raw paragraph text with law name and section reference.
This is NOT done at query time.

IDEMPOTENCY:
Each chunk has a stable ID (hash of law_code + section + subsection).
Before embedding, we check if the chunk already exists in Qdrant with
the same content hash. If so, we skip re-embedding (no wasted API calls).
"""
from __future__ import annotations
import logging
import os
import sys
import time

from qdrant_client.models import PointStruct

# Add parent to path for shared imports
sys.path.insert(0, "/app")

from shared.qdrant_utils import (
    get_qdrant_client,
    ensure_collection,
    upsert_points,
    point_exists_with_hash,
)
from ingest.chunker import chunk_law
from ingest.embedder import get_embedding_provider
from ingest.fetcher import load_all_laws

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


def run_ingestion() -> None:
    """
    Main ingestion pipeline.

    Flow:
    1. Wait for Qdrant
    2. Load embedding provider
    3. Load all laws
    4. Chunk each law
    5. For each chunk:
       a. Check if already ingested with same content hash
       b. If changed/new: generate embedding, upsert to Qdrant
    6. Log statistics
    """
    logger.info("=== Starting Danish Legal RAG Ingestion ===")

    # Step 1: Wait for Qdrant
    wait_for_qdrant()
    qdrant = get_qdrant_client()

    # Step 2: Load embedding provider
    # EMBEDDING STEP: Provider is loaded here. Embeddings will be generated below.
    embedder = get_embedding_provider()
    logger.info(f"Embedding provider: {embedder.model_name} (vector_size={embedder.vector_size})")

    # Ensure collection exists with correct vector dimensions
    ensure_collection(qdrant, embedder.vector_size)

    # Step 3: Load law texts
    laws = load_all_laws()

    # Step 4 & 5: Chunk, embed, and upsert
    total_new = 0
    total_skipped = 0
    total_chunks = 0

    for law_data in laws:
        # Chunk: one LegalChunk per provision
        chunks = chunk_law(law_data, embedding_model=embedder.model_name)
        total_chunks += len(chunks)

        # Identify which chunks need (re-)embedding
        chunks_to_embed = []
        for chunk in chunks:
            if point_exists_with_hash(qdrant, chunk.id, chunk.embedding_content_hash):
                logger.debug(f"Skipping unchanged chunk: {chunk.citation_label}")
                total_skipped += 1
            else:
                chunks_to_embed.append(chunk)

        if not chunks_to_embed:
            logger.info(f"All chunks for {law_data['law_name']} are up to date, skipping")
            continue

        logger.info(
            f"Embedding {len(chunks_to_embed)} new/changed chunks "
            f"from {law_data['law_name']} "
            f"(skipping {len(chunks) - len(chunks_to_embed)} unchanged)"
        )

        # EMBEDDING STEP: Generate embeddings for new/changed chunks
        # We embed the ENRICHED text (law name + section + paragraph text)
        # NOT just the raw paragraph text.
        embedding_texts = [chunk.compute_embedding_text() for chunk in chunks_to_embed]

        logger.info(f"Generating embeddings for {len(embedding_texts)} texts...")
        vectors = embedder.embed(embedding_texts)
        logger.info("Embeddings generated successfully")

        # Build Qdrant points
        points = []
        for chunk, vector in zip(chunks_to_embed, vectors):
            point = PointStruct(
                id=chunk.id,
                vector=vector,
                payload=chunk.to_qdrant_payload(),
            )
            points.append(point)

        # Upsert to Qdrant (idempotent by point ID)
        upsert_points(qdrant, points)
        total_new += len(chunks_to_embed)

    logger.info("=== Ingestion Complete ===")
    logger.info(f"Total chunks processed: {total_chunks}")
    logger.info(f"New/updated chunks: {total_new}")
    logger.info(f"Unchanged (skipped): {total_skipped}")


if __name__ == "__main__":
    run_ingestion()
