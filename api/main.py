"""
Danish Legal RAG - REST API

FastAPI application exposing the RAG system via HTTP.

Endpoints:
  POST /ask    - Ask a natural language question, get answer + references
  POST /search - Semantic search without answer generation
  GET  /laws   - List all ingested laws
  GET  /health - Health check
"""
from __future__ import annotations
import logging
import sys

# Add app root to path
sys.path.insert(0, "/app")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from shared.models import AskRequest, AskResponse, SearchRequest, SearchResponse
from shared.qdrant_utils import get_qdrant_client, get_all_laws
from api.rag import ask, search
from api.embeddings import get_query_embedder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

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
    """Pre-warm the embedding model at startup."""
    logger.info("Starting Danish Legal RAG API...")
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


@app.get("/laws")
async def list_laws():
    """List all laws currently ingested in the system."""
    try:
        qdrant = get_qdrant_client()
        laws = get_all_laws(qdrant)
        return {"laws": laws, "count": len(laws)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def root():
    return {
        "service": "Danish Legal RAG API",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": ["/ask", "/search", "/laws", "/health"],
    }
