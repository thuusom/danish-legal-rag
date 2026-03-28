"""
RAG (Retrieval-Augmented Generation) pipeline.

Flow:
1. QUERY EMBEDDING:  Embed the user's question
2. RETRIEVAL:        Search Qdrant for semantically similar legal provisions
3. CONTEXT BUILDING: Collect retrieved chunks with full legal references
4. ANSWER GENERATION: Call LLM with retrieved context + system prompt + style guide

Answer style
------------
The base system prompt (RAG_BASE_PROMPT) enforces legal accuracy rules.
On top of that, the file pointed to by ANSWER_STYLE_FILE (default: /app/answer-style.md)
is appended at runtime.  Edit that file freely – changes take effect on the next
API call with NO restart required (the file is read fresh each request).

LLM providers
-------------
Set LLM_PROVIDER in .env to one of:
  anthropic  – Claude API (default)
  openai     – OpenAI ChatCompletion
  ollama     – Local Ollama server via its OpenAI-compatible /v1 endpoint
  mock       – Template fallback, no API key needed

Ollama example (.env):
  LLM_PROVIDER=ollama
  OLLAMA_BASE_URL=http://woodcock2.vpn:7869/v1
  OLLAMA_MODEL=llama3.3:70b
"""
from __future__ import annotations
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from shared.models import AskRequest, AskResponse, LegalReference, SearchResponse
from shared.qdrant_utils import get_qdrant_client, search_similar
from api.embeddings import get_query_embedder

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Base system prompt – enforces legal accuracy, never changes
# ---------------------------------------------------------------------------
RAG_BASE_PROMPT = """Du er en dansk juridisk assistent, der specialiserer sig i dansk skatte- og regnskabsret.

Din opgave er at besvare spørgsmål baseret KUN på de lovtekster og bestemmelser, som er indeholdt i den kontekst, du har fået.

Ufravigelige regler:
1. Du må ALDRIG opfinde, gætte eller ekstrapolere juridisk information.
   Baser UDELUKKENDE svaret på den givne kontekst.
2. Du SKAL altid angive præcise juridiske referencer (lov, §, stk.) for hvert udsagn.
3. Hvis konteksten er utilstrækkelig til at besvare spørgsmålet, skal du sige det klart og tydeligt.
4. Svar på dansk.
5. Citér relevante tekstuddrag, der understøtter dit svar.

VIGTIG ANSVARSFRASKRIVELSE: Dette er et teknisk demonstrationssystem.
Søg altid professionel juridisk rådgivning for konkrete sager."""

NO_SOURCES_MESSAGE = """Jeg kan desværre ikke finde tilstrækkelige juridiske bestemmelser i den tilgængelige database til at besvare dette spørgsmål fyldestgørende.

De ingested lovtekster dækker:
- Afskrivningsloven (AFL): Skattemæssige afskrivninger inkl. immaterielle aktiver og software
- Årsregnskabsloven (ARL): Regnskabsmæssig behandling af immaterielle aktiver

Kontakt en skatterådgiver eller revisor for specifik juridisk vejledning."""


# ---------------------------------------------------------------------------
# Answer style – loaded from file on every request (hot-reloadable)
# ---------------------------------------------------------------------------

def _load_answer_style() -> str:
    """
    Load the answer style guide from answer-style.md.

    Path priority:
    1. ANSWER_STYLE_FILE env var
    2. /app/answer-style.md  (default inside Docker)
    3. ./answer-style.md     (local development fallback)

    Returns empty string if no style file is found (base prompt only).
    The file is read fresh on every call so edits take effect immediately.
    """
    candidates = [
        os.environ.get("ANSWER_STYLE_FILE"),
        "/app/answer-style.md",
        str(Path(__file__).parent.parent / "answer-style.md"),
    ]
    for path in candidates:
        if path and Path(path).exists():
            try:
                content = Path(path).read_text(encoding="utf-8").strip()
                logger.debug(f"Loaded answer style from {path} ({len(content)} chars)")
                return content
            except Exception as e:
                logger.warning(f"Could not read answer style file {path}: {e}")
    logger.debug("No answer-style.md found – using base prompt only")
    return ""


def build_system_prompt() -> str:
    """
    Combine the immutable base legal prompt with the hot-reloadable style guide.

    The base prompt enforces legal accuracy (never hallucinate, always cite).
    The style guide controls tone, format, examples, etc.
    Keeping them separate means the style can be changed without touching core logic.
    """
    style = _load_answer_style()
    if not style:
        return RAG_BASE_PROMPT
    return f"{RAG_BASE_PROMPT}\n\n---\n\n{style}"


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

def build_context_text(results: list[dict]) -> str:
    """Format retrieved Qdrant chunks as numbered context block for the LLM."""
    parts = []
    for i, r in enumerate(results, 1):
        p = r["payload"]
        parts.append(
            f"[Kilde {i}] {p.get('citation_label', 'Ukendt reference')}\n"
            f"Lov: {p.get('law_name', '')} ({p.get('law_number', '')})\n"
            f"Tekst: {p.get('text', '')}\n"
            f"URL: {p.get('source_url', 'Ikke tilgængelig')}"
        )
    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# LLM provider dispatch
# ---------------------------------------------------------------------------

def call_llm(question: str, context: str) -> tuple[str, str]:
    """
    Call the configured LLM provider.
    Returns (answer_text, model_name_used).

    Provider selection via LLM_PROVIDER env var:
      anthropic  – Claude API (default)
      openai     – OpenAI ChatCompletion
      ollama     – Local Ollama via OpenAI-compatible /v1 endpoint
      mock       – No LLM, returns raw context (for testing)
    """
    provider = os.environ.get("LLM_PROVIDER", "anthropic").lower()

    # Build the user prompt once (same regardless of provider)
    user_prompt = (
        f"Kontekst (relevante lovbestemmelser):\n\n{context}\n\n"
        f"---\n\n"
        f"Spørgsmål: {question}\n\n"
        f"Besvar spørgsmålet baseret udelukkende på ovenstående lovbestemmelser. "
        f"Angiv præcise referencer og følg svarstilen beskrevet i systemprompt."
    )

    if provider == "anthropic":
        return _call_anthropic(user_prompt)
    elif provider == "openai":
        return _call_openai(user_prompt)
    elif provider == "ollama":
        return _call_ollama(user_prompt)
    else:
        return _mock_answer(question, context), "mock"


def _call_anthropic(user_prompt: str) -> tuple[str, str]:
    """Call Anthropic Claude API."""
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set, falling back to mock")
        return _mock_answer("", user_prompt), "mock"

    model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-5")
    client = anthropic.Anthropic(api_key=api_key)
    system_prompt = build_system_prompt()

    logger.info(f"Calling Anthropic {model} (system_prompt={len(system_prompt)} chars)")
    message = client.messages.create(
        model=model,
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return message.content[0].text, model


def _call_openai(user_prompt: str) -> tuple[str, str]:
    """Call OpenAI ChatCompletion API."""
    import openai

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY not set, falling back to mock")
        return _mock_answer("", user_prompt), "mock"

    model = os.environ.get("OPENAI_MODEL", "gpt-4o")
    client = openai.OpenAI(api_key=api_key)
    system_prompt = build_system_prompt()

    logger.info(f"Calling OpenAI {model}")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=2048,
    )
    return response.choices[0].message.content, model


def _call_ollama(user_prompt: str) -> tuple[str, str]:
    """
    Call a local Ollama server via its OpenAI-compatible /v1 endpoint.

    Ollama exposes the same REST interface as OpenAI's ChatCompletion API,
    so we use the openai Python client with a custom base_url.

    Configuration (in .env):
      OLLAMA_BASE_URL=http://woodcock2.vpn:7869/v1
      OLLAMA_MODEL=llama3.3:70b

    Recommended models for Danish legal text (pull with: ollama pull <model>):
      llama3.3:70b    – Best: strong Danish, excellent instruction-following,
                        good at structured output with references. ~40 GB RAM.
      qwen2.5:32b     – Good: multilingual, strong at structured tasks. ~20 GB.
      qwen2.5:14b     – Lighter alternative to qwen2.5:32b. ~9 GB RAM.
      mistral-nemo    – Fast, decent Danish, lower memory footprint. ~8 GB.
      gemma3:27b      – Google model, good multilingual reasoning. ~17 GB.

    Note: Ollama does not require a real API key.
    We pass "ollama" as a dummy value to satisfy the openai client.
    """
    import openai

    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    model = os.environ.get("OLLAMA_MODEL", "llama3.3:70b")
    system_prompt = build_system_prompt()

    logger.info(f"Calling Ollama at {base_url} model={model}")

    # openai client works with Ollama's /v1 endpoint out of the box
    client = openai.OpenAI(base_url=base_url, api_key="ollama")

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=2048,
            temperature=0.1,   # Low temperature for factual/legal answers
        )
        return response.choices[0].message.content, f"ollama/{model}"
    except Exception as e:
        logger.error(f"Ollama call failed: {e}")
        raise RuntimeError(
            f"Ollama at {base_url} with model '{model}' failed: {e}. "
            f"Check that Ollama is running and the model is pulled "
            f"(ollama pull {model})."
        ) from e


def _mock_answer(question: str, context: str) -> str:
    """
    Template-based fallback when no LLM API key is configured.
    Still uses real retrieved context – references are genuine.
    """
    return (
        "**BEMÆRK: Mock-tilstand** – Ingen LLM er konfigureret. "
        "Indstil LLM_PROVIDER (anthropic/openai/ollama) i .env.\n\n"
        "Følgende lovbestemmelser blev fundet og ville blive sendt til LLM:\n\n"
        f"{context}\n\n"
        "---\n"
        "*Konfigurér en LLM-provider for at få et formuleret svar.*"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def results_to_references(results: list[dict]) -> list[LegalReference]:
    """Convert Qdrant search results to structured LegalReference objects."""
    references = []
    for r in results:
        p = r["payload"]
        ref = LegalReference(
            law=p.get("law_name", ""),
            law_code=p.get("law_code", ""),
            section=p.get("section", ""),
            subsection=p.get("subsection"),
            item=p.get("item"),
            title=p.get("title"),
            quote=p.get("text", ""),
            citation_label=p.get("citation_label", ""),
            source_url=p.get("source_url"),
            score=r.get("score"),
        )
        references.append(ref)
    return references


# ---------------------------------------------------------------------------
# Public pipeline entry points
# ---------------------------------------------------------------------------

async def ask(request: AskRequest) -> AskResponse:
    """
    Main RAG pipeline for POST /ask.

    1. QUERY EMBEDDING:   User question → vector (via get_query_embedder())
    2. RETRIEVAL:         Vector → top-k chunks from Qdrant
    3. CONTEXT BUILDING:  Chunks → formatted text block
    4. ANSWER GENERATION: Context + question → LLM → structured response
    """
    logger.info(f"Processing question: {request.question}")

    # 1. Embed the question at query time
    embedder = get_query_embedder()
    query_vector = embedder.embed_query(request.question)

    # 2. Retrieve semantically similar legal provisions
    qdrant = get_qdrant_client()
    results = search_similar(
        qdrant,
        query_vector=query_vector,
        limit=request.limit,
        filter_law=request.filter_law,
    )

    if not results:
        logger.warning("No relevant sources found for question")
        return AskResponse(
            answer=NO_SOURCES_MESSAGE,
            references=[],
            retrieved_context=[],
            question=request.question,
            model_used="none",
        )

    logger.info(
        f"Retrieved {len(results)} chunks "
        f"(top score: {results[0]['score']:.3f}, "
        f"provider: {os.environ.get('LLM_PROVIDER', 'anthropic')})"
    )

    # 3. Build context and call LLM
    context_text = build_context_text(results)
    answer, model_used = call_llm(request.question, context_text)

    return AskResponse(
        answer=answer,
        references=results_to_references(results),
        retrieved_context=[r["payload"] for r in results],
        question=request.question,
        model_used=model_used,
    )


async def search(request) -> SearchResponse:
    """Semantic search without answer generation (POST /search)."""
    from shared.models import SearchRequest
    embedder = get_query_embedder()
    query_vector = embedder.embed_query(request.query)
    qdrant = get_qdrant_client()
    results = search_similar(
        qdrant,
        query_vector=query_vector,
        limit=request.limit,
        filter_law=request.filter_law,
    )
    return SearchResponse(results=results_to_references(results), query=request.query)
