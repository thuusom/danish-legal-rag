"""
RAG (Retrieval-Augmented Generation) pipeline.

Flow:
1. QUERY EMBEDDING: Embed the user's question
2. RETRIEVAL: Search Qdrant for semantically similar legal provisions
3. CONTEXT BUILDING: Collect retrieved chunks with full legal references
4. ANSWER GENERATION: Call LLM with retrieved context + strict prompt

The LLM is instructed to ONLY answer based on retrieved sources,
never to invent legal information, and to cite sources explicitly.

If sources are insufficient, the system says so honestly.
"""
from __future__ import annotations
import logging
import os
from typing import Optional

from shared.models import AskRequest, AskResponse, LegalReference, SearchResponse
from shared.qdrant_utils import get_qdrant_client, search_similar
from api.embeddings import get_query_embedder

logger = logging.getLogger(__name__)

RAG_SYSTEM_PROMPT = """Du er en dansk juridisk assistent, der specialiserer sig i dansk skatte- og regnskabsret.

Din opgave er at besvare spørgsmål baseret KUN på de lovtekster og bestemmelser, som er indeholdt i den kontekst, du har fået.

Regler du SKAL følge:
1. Du må ALDRIG opfinde eller gætte juridisk information. Baser kun svaret på den givne kontekst.
2. Du SKAL altid angive præcise juridiske referencer (lov, §, stk.) for hvert udsagn.
3. Hvis konteksten er utilstrækkelig til at besvare spørgsmålet, skal du sige det klart og tydeligt.
4. Svar på dansk.
5. Vær præcis og konkret. Undgå vage formuleringer.
6. Citér relevante tekstuddrag, der understøtter dit svar.

Format:
- Start med et direkte svar på spørgsmålet
- Henvis eksplicit til de paragraffer, der danner grundlag for svaret
- Angiv eventuelt begrænsninger eller forbehold

VIGTIG ANSVARSFRASKRIVELSE: Dette er et teknisk demonstration-system. Søg altid professionel juridisk rådgivning for konkrete sager."""

NO_SOURCES_MESSAGE = """Jeg kan desværre ikke finde tilstrækkelige juridiske bestemmelser i den tilgængelige database til at besvare dette spørgsmål fyldestgørende.

De ingested lovtekster dækker:
- Afskrivningsloven (AFL): Skattemæssige afskrivninger inkl. immaterielle aktiver og software
- Årsregnskabsloven (ARL): Regnskabsmæssig behandling af immaterielle aktiver

Kontakt en skatterådgiver eller revisor for specifik juridisk vejledning."""


def build_context_text(results: list[dict]) -> str:
    """Format retrieved chunks as context for the LLM."""
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


def call_llm(question: str, context: str) -> tuple[str, str]:
    """
    Call the configured LLM provider.
    Returns (answer_text, model_name).

    Providers:
    - anthropic (default): Claude API
    - openai: OpenAI ChatCompletion
    - mock: Template-based fallback (no API key needed)
    """
    provider = os.environ.get("LLM_PROVIDER", "anthropic").lower()

    user_prompt = f"""Kontekst (relevante lovbestemmelser):

{context}

---

Spørgsmål: {question}

Besvar spørgsmålet baseret udelukkende på ovenstående lovbestemmelser. Angiv præcise referencer."""

    if provider == "anthropic":
        return _call_anthropic(user_prompt)
    elif provider == "openai":
        return _call_openai(user_prompt)
    else:
        return _mock_answer(question, context), "mock"


def _call_anthropic(user_prompt: str) -> tuple[str, str]:
    """Call Anthropic Claude API."""
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set, falling back to mock")
        return _mock_answer("", user_prompt), "mock"

    model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-6")
    client = anthropic.Anthropic(api_key=api_key)

    message = client.messages.create(
        model=model,
        max_tokens=2048,
        system=RAG_SYSTEM_PROMPT,
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

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": RAG_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=2048,
    )
    return response.choices[0].message.content, model


def _mock_answer(question: str, context: str) -> str:
    """
    Template-based fallback answer when no LLM API key is configured.
    Still uses real retrieved context - references are genuine.
    """
    return (
        "BEMÆRK: Dette svar er genereret uden LLM (mock-tilstand). "
        "Indstil ANTHROPIC_API_KEY eller OPENAI_API_KEY for AI-genererede svar.\n\n"
        "Baseret på de fundne juridiske bestemmelser:\n\n"
        f"{context}\n\n"
        "For præcise svar baseret på disse bestemmelser, konfigurér venligst en LLM-provider."
    )


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


async def ask(request: AskRequest) -> AskResponse:
    """
    Main RAG pipeline for the /ask endpoint.

    1. QUERY EMBEDDING: Embed the question using get_query_embedder()
    2. RETRIEVAL: Find similar chunks in Qdrant
    3. ANSWER GENERATION: Call LLM with context
    """
    logger.info(f"Processing question: {request.question}")

    # Step 1: QUERY EMBEDDING
    # The user's question is embedded here at query time
    embedder = get_query_embedder()
    query_vector = embedder.embed_query(request.question)

    # Step 2: RETRIEVAL
    # Find semantically similar legal provisions
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

    logger.info(f"Retrieved {len(results)} relevant chunks (top score: {results[0]['score']:.3f})")

    # Step 3: BUILD CONTEXT
    context_text = build_context_text(results)

    # Step 4: ANSWER GENERATION
    answer, model_used = call_llm(request.question, context_text)

    # Build structured references (always included)
    references = results_to_references(results)

    return AskResponse(
        answer=answer,
        references=references,
        retrieved_context=[r["payload"] for r in results],
        question=request.question,
        model_used=model_used,
    )


async def search(request) -> SearchResponse:
    """Semantic search without answer generation."""
    from shared.models import SearchRequest
    embedder = get_query_embedder()
    query_vector = embedder.embed_query(request.query)
    qdrant = get_qdrant_client()
    results = search_similar(qdrant, query_vector=query_vector, limit=request.limit, filter_law=request.filter_law)
    references = results_to_references(results)
    return SearchResponse(results=references, query=request.query)
