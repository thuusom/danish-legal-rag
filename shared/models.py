"""
Shared domain models for the Danish Legal RAG system.
"""
from __future__ import annotations

import hashlib
import os
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


def get_effective_strategy(override: Optional[str] = None) -> str:
    """
    Resolve the retrieval strategy to use for a request.

    Priority:
    1. Per-request override (from request body)
    2. RETRIEVAL_STRATEGY env var
    3. Default: "dense"
    """
    if override:
        return override.lower()
    return os.environ.get("RETRIEVAL_STRATEGY", "dense").lower()


class LegalChunk(BaseModel):
    """
    Represents a chunk of a Danish legal text.
    Each chunk corresponds to one paragraph (§) or sub-section.

    References are preserved fully so no legal citation is lost
    even if only part of the text is retrieved.
    """
    # Identity
    id: str = Field(description="Stable UUID derived from law_code + section + subsection")

    # Legal reference metadata (preserved separately from embedding)
    law_code: str = Field(description="Short law code, e.g. 'AFL' for Afskrivningsloven")
    law_name: str = Field(description="Full law name in Danish")
    law_title: str = Field(description="Official title of the law")
    chapter: Optional[str] = Field(default=None, description="Chapter number/title if applicable")
    section: str = Field(description="Paragraph number, e.g. '§ 40'")
    subsection: Optional[str] = Field(default=None, description="Sub-section (stk.), e.g. 'stk. 2'")
    item: Optional[str] = Field(default=None, description="Item/letter (nr./litra), e.g. 'nr. 1'")
    title: Optional[str] = Field(default=None, description="Heading/title of the section if available")

    # Content
    text: str = Field(description="Full text of this legal provision")
    citation_label: str = Field(description="Human-readable citation, e.g. 'Afskrivningsloven § 40, stk. 2'")

    # Source
    source_url: Optional[str] = Field(default=None, description="Canonical URL at retsinformation.dk")
    effective_date: Optional[str] = Field(default=None, description="Date the provision became effective")
    law_number: Optional[str] = Field(default=None, description="Official law number, e.g. 'LBK nr 1147 af 29/08/2016'")

    # Embedding tracking (for idempotent ingestion)
    embedding_model: str = Field(description="Name of the embedding model used")
    embedding_content_hash: str = Field(description="SHA256 of the text used as embedding input")

    # Provenance metadata (Issue #22 — populated by the live retsinformation fetcher)
    # All optional: pre-fetcher chunks lack these and will backfill on next ingestion.
    ingested_at: Optional[datetime] = Field(
        default=None,
        description="UTC timestamp at which this chunk was ingested",
    )
    law_version_date: Optional[date] = Field(
        default=None,
        description="Effective date of the law version this chunk was extracted from "
                    "(retsinformation API `effective_date` top-level field)",
    )
    law_version_number: Optional[int] = Field(
        default=None,
        description="Version number of the law as reported by the retsinformation API",
    )
    eli: Optional[str] = Field(
        default=None,
        description="European Legislation Identifier path, e.g. 'eli/lta/2016/1147'",
    )
    retsinformation_law_id: Optional[str] = Field(
        default=None,
        description="UUID identifying the law (stable across versions) in retsinformation-api.dk",
    )
    retsinformation_paragraph_id: Optional[str] = Field(
        default=None,
        description="Stable paragraph anchor id used by retsinformation.dk's HTML viewer",
    )

    def compute_embedding_text(self) -> str:
        """
        Construct the text that will be embedded.

        Strategy: We enrich the embedding text with law name and section reference
        so semantic search can match both topic-based and reference-based queries.
        The raw reference fields are stored separately in the payload.

        Example embedding text:
          "Afskrivningsloven § 40, stk. 2 [EDB-programmer, software]:
           Udgifter til erhvervelse af EDB-programmer..."
        """
        parts = [f"{self.law_name} {self.section}"]
        if self.subsection:
            parts[0] += f", {self.subsection}"
        if self.title:
            parts[0] += f" [{self.title}]"
        parts.append(self.text)
        return "\n".join(parts)

    def compute_content_hash(self) -> str:
        """SHA256 hash of the embedding input text, used for idempotent re-ingestion."""
        return hashlib.sha256(self.compute_embedding_text().encode("utf-8")).hexdigest()

    def to_qdrant_payload(self) -> dict:
        """
        Serialize to Qdrant point payload (all fields except the vector itself).

        New optional provenance fields (Issue #22) are only included when
        non-null so we don't bloat payloads for chunks ingested before the
        live fetcher landed. ``ingested_at`` and ``law_version_date`` are
        serialised to ISO 8601 strings — Qdrant payloads are JSON, not
        Python objects, and downstream consumers (frontend, MCP) expect
        strings per the OpenAPI contract.
        """
        payload: dict = {
            "id": self.id,
            "law_code": self.law_code,
            "law_name": self.law_name,
            "law_title": self.law_title,
            "chapter": self.chapter,
            "section": self.section,
            "subsection": self.subsection,
            "item": self.item,
            "title": self.title,
            "text": self.text,
            "citation_label": self.citation_label,
            "source_url": self.source_url,
            "effective_date": self.effective_date,
            "law_number": self.law_number,
            "embedding_model": self.embedding_model,
            "embedding_content_hash": self.embedding_content_hash,
        }
        if self.ingested_at is not None:
            payload["ingested_at"] = self.ingested_at.isoformat()
        if self.law_version_date is not None:
            payload["law_version_date"] = self.law_version_date.isoformat()
        if self.law_version_number is not None:
            payload["law_version_number"] = self.law_version_number
        if self.eli is not None:
            payload["eli"] = self.eli
        if self.retsinformation_law_id is not None:
            payload["retsinformation_law_id"] = self.retsinformation_law_id
        if self.retsinformation_paragraph_id is not None:
            payload["retsinformation_paragraph_id"] = self.retsinformation_paragraph_id
        return payload


class AskRequest(BaseModel):
    question: str = Field(description="Natural language question in Danish")
    limit: int = Field(default=8, ge=1, le=20, description="Max number of sources to retrieve")
    filter_law: Optional[str] = Field(default=None, description="Optional: filter by law_code, e.g. 'AFL'")
    retrieval_strategy: Optional[Literal["dense", "hybrid"]] = Field(
        default=None,
        description="Retrieval strategy override. Omit to use server default (RETRIEVAL_STRATEGY env var).",
    )


class LegalReference(BaseModel):
    law: str
    law_code: str
    section: str
    subsection: Optional[str] = None
    item: Optional[str] = None
    title: Optional[str] = None
    quote: str
    citation_label: str
    source_url: Optional[str] = None
    score: Optional[float] = None
    # Provenance fields surfaced for the frontend (Issue #22)
    eli: Optional[str] = Field(
        default=None,
        description="ELI path, e.g. 'eli/lta/2016/1147', for deep-linking to retsinformation.dk",
    )
    law_version_date: Optional[date] = Field(
        default=None,
        description="Effective date of the law version this reference was retrieved from",
    )


class AskResponse(BaseModel):
    answer: str
    references: list[LegalReference]
    retrieved_context: list[dict]
    question: str
    model_used: str


class StreamAskRequest(BaseModel):
    """Request body for POST /ask/stream — like AskRequest but with optional conversation history."""
    question: str = Field(description="Natural language question in Danish")
    limit: int = Field(default=8, ge=1, le=20, description="Max number of sources to retrieve")
    filter_law: Optional[str] = Field(default=None, description="Optional: filter by law_code, e.g. 'AFL'")
    retrieval_strategy: Optional[Literal["dense", "hybrid"]] = Field(
        default=None,
        description="Retrieval strategy override. Omit to use server default (RETRIEVAL_STRATEGY env var).",
    )
    history: Optional[list[dict]] = Field(
        default=None,
        description="Optional conversation history for multi-turn context. Each entry has 'role' and 'content'.",
    )


class StreamChunkEvent(BaseModel):
    """SSE event: partial answer text chunk."""
    type: Literal["chunk"] = "chunk"
    data: str


class StreamReferencesEvent(BaseModel):
    """SSE event: full reference array, sent once after answer completion."""
    type: Literal["references"] = "references"
    data: list[LegalReference]


class StreamDoneEvent(BaseModel):
    """SSE event: completion signal."""
    type: Literal["done"] = "done"
    data: dict


class StreamErrorEvent(BaseModel):
    """SSE event: error, sent on failure before stream closes."""
    type: Literal["error"] = "error"
    data: dict


class SearchRequest(BaseModel):
    query: str
    limit: int = Field(default=5, ge=1, le=20)
    filter_law: Optional[str] = None
    retrieval_strategy: Optional[Literal["dense", "hybrid"]] = Field(
        default=None,
        description="Retrieval strategy override. Omit to use server default (RETRIEVAL_STRATEGY env var).",
    )


class SearchResponse(BaseModel):
    results: list[LegalReference]
    query: str


class LawSummary(BaseModel):
    """Summary entry for the GET /laws endpoint."""
    law_code: str
    law_name: str
    law_title: Optional[str] = None
    law_number: Optional[str] = None
    source_url: Optional[str] = None
    # Aggregate provenance (Issue #22) — first non-null wins across the law's chunks
    eli: Optional[str] = Field(
        default=None,
        description="ELI path aggregated across the law's chunks",
    )
    law_version_date: Optional[date] = Field(
        default=None,
        description="Effective date of the law version currently ingested",
    )
    latest_ingested_at: Optional[datetime] = Field(
        default=None,
        description="Most recent ingestion timestamp across this law's chunks",
    )


class LawsResponse(BaseModel):
    """Response body for GET /laws."""
    laws: list[LawSummary]
    count: int
