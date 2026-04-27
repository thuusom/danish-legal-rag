"""
Danish Legal RAG - REST API

FastAPI application exposing the RAG system via HTTP.

Endpoints:
  POST /ask        - Ask a natural language question, get answer + references
  POST /ask/stream - Ask with streaming SSE response (token-by-token)
  POST /search     - Semantic search without answer generation
  GET  /laws       - List all ingested laws
  GET  /health     - Health check
"""
from __future__ import annotations

import logging
import os
import sys
import time

# Add app root to path
sys.path.insert(0, "/app")


from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from api.embeddings import get_query_embedder
from api.rag import (
    NO_SOURCES_MESSAGE,
    ask,
    build_context_text,
    call_llm_stream,
    get_effective_strategy,
    get_model_name,
    results_to_references,
    search,
)
from shared.models import (
    AskRequest,
    AskResponse,
    LawsResponse,
    SearchRequest,
    SearchResponse,
    StreamAskRequest,
    StreamChunkEvent,
    StreamDoneEvent,
    StreamErrorEvent,
    StreamReferencesEvent,
)
from shared.qdrant_utils import get_all_laws, get_qdrant_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _wait_for_qdrant(max_retries: int = 30, delay: float = 2.0) -> None:
    """Block at startup until Qdrant is reachable (no Docker healthcheck needed)."""
    from qdrant_client import QdrantClient
    host = os.environ.get("QDRANT_HOST", "localhost")
    port = int(os.environ.get("QDRANT_PORT", "6333"))
    for attempt in range(max_retries):
        try:
            QdrantClient(host=host, port=port).get_collections()
            logger.info("Qdrant is ready")
            return
        except Exception as exc:
            logger.info(f"Waiting for Qdrant ({attempt + 1}/{max_retries}): {exc}")
            time.sleep(delay)
    raise RuntimeError("Qdrant did not become ready in time")

app = FastAPI(
    title="Dansk Juridisk RAG API",
    description=(
        "RAG-baseret API til søgning og besvarelse af spørgsmål om dansk "
        "skatte- og regnskabslovgivning. Svarene baseres udelukkende på "
        "indlæste lovtekster fra Afskrivningsloven og Årsregnskabsloven."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """Wait for Qdrant, then pre-warm the embedding model."""
    logger.info("Starting Danish Legal RAG API...")
    _wait_for_qdrant()
    try:
        embedder = get_query_embedder()
        logger.info(f"Embedding model loaded: {embedder.model_name}")
    except Exception as e:
        logger.error(f"Failed to load embedding model: {e}")


@app.get("/health")
async def health():
    """Health check endpoint."""
    try:
        qdrant = get_qdrant_client()
        collections = qdrant.get_collections()
        return {
            "status": "ok",
            "qdrant": "connected",
            "collections": [c.name for c in collections.collections],
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Qdrant unavailable: {e}")


@app.post("/ask", response_model=AskResponse)
async def ask_endpoint(request: AskRequest):
    """
    Ask a natural language question about Danish tax and accounting law.

    Returns:
    - answer: Explanation in Danish
    - references: Precise legal references (law, §, stk.)
    - retrieved_context: Raw retrieved chunks from Qdrant
    """
    try:
        return await ask(request)
    except Exception as e:
        logger.error(f"Error processing question: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ask/stream")
async def ask_stream_endpoint(request: StreamAskRequest):
    """
    Streaming version of /ask. Returns Server-Sent Events.

    SSE event sequence:
    1. Zero or more StreamChunkEvent (partial answer text)
    2. One StreamReferencesEvent (full reference array)
    3. One StreamDoneEvent (completion signal)
    On error: one StreamErrorEvent, then stream closes.
    """
    from shared.sparse import get_sparse_provider

    async def event_generator():
        try:
            # 1. Embed the question
            embedder = get_query_embedder()
            query_vector = embedder.embed_query(request.question)

            # 1b. Sparse vector if hybrid
            strategy = get_effective_strategy(request.retrieval_strategy)
            sparse_vec = None
            if strategy == "hybrid":
                sparse_vec = get_sparse_provider().embed_single(request.question)

            # 2. Retrieve
            qdrant = get_qdrant_client()
            from shared.qdrant_utils import search_similar
            results = search_similar(
                qdrant,
                query_vector=query_vector,
                limit=request.limit,
                filter_law=request.filter_law,
                sparse_vector=sparse_vec,
            )

            if not results:
                # No sources: send the no-sources message as a single chunk, then done
                event = StreamChunkEvent(data=NO_SOURCES_MESSAGE)
                yield f"data: {event.model_dump_json()}\n\n"
                refs_event = StreamReferencesEvent(data=[])
                yield f"data: {refs_event.model_dump_json()}\n\n"
                done_event = StreamDoneEvent(data={"model_used": "none"})
                yield f"data: {done_event.model_dump_json()}\n\n"
                return

            # 3. Build context and stream LLM answer
            context_text = build_context_text(results)
            references = results_to_references(results)

            for chunk_text in call_llm_stream(
                request.question,
                context_text,
                history=request.history,
            ):
                event = StreamChunkEvent(data=chunk_text)
                yield f"data: {event.model_dump_json()}\n\n"

            # 4. Send references
            refs_event = StreamReferencesEvent(data=references)
            yield f"data: {refs_event.model_dump_json()}\n\n"

            # 5. Send done
            model_used = get_model_name()
            done_event = StreamDoneEvent(data={"model_used": model_used})
            yield f"data: {done_event.model_dump_json()}\n\n"

        except Exception as e:
            logger.error(f"Streaming error: {e}", exc_info=True)
            error_event = StreamErrorEvent(data={"detail": str(e)})
            yield f"data: {error_event.model_dump_json()}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/search", response_model=SearchResponse)
async def search_endpoint(request: SearchRequest):
    """
    Semantic search in the legal database without answer generation.
    Returns ranked list of relevant legal provisions.
    """
    try:
        return await search(request)
    except Exception as e:
        logger.error(f"Error in search: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/laws", response_model=LawsResponse)
async def list_laws() -> LawsResponse:
    """
    List all laws currently ingested in the system.

    Each entry carries aggregate provenance fields (`eli`,
    `law_version_date`, `latest_ingested_at`) computed across the law's
    chunks — useful for the UI's "law catalogue" page.
    """
    try:
        qdrant = get_qdrant_client()
        laws = get_all_laws(qdrant)
        return LawsResponse(laws=laws, count=len(laws))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def root():
    return {
        "service": "Danish Legal RAG API",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": ["/ask", "/ask/stream", "/search", "/laws", "/health"],
    }
